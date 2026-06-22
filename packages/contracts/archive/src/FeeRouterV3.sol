// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * FeeRouterV3.sol — Multi-Asset + Oracle Compliance Guard
 * Base Network (8453 / 84532)
 *
 * Supporta: ETH, USDC, USDT, cbBTC, DEGEN, qualsiasi ERC-20
 *
 * Architettura:
 *   1. transferWithOracle(token, amount, recipient, oracleSignature)
 *      → ECDSA.recover verifica firma Oracle
 *      → nonce anti-replay + deadline 60s
 *      → split atomico 99.5% / 0.5%
 *   2. transferETHWithOracle(recipient, oracleSignature)
 *      → stessa logica per ETH nativo
 *   3. transferWithPermit2(TransferParams)
 *      → Permit2 + Oracle in 1 TX (da versione precedente)
 */

import {Ownable}          from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}           from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}        from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard}  from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ECDSA}            from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import {EIP712}           from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";

// ── Permit2 interface (minimale) ───────────────────────────────────────────
interface ISignatureTransfer {
    struct TokenPermissions     { address token; uint256 amount; }
    struct PermitTransferFrom   { TokenPermissions permitted; uint256 nonce; uint256 deadline; }
    struct SignatureTransferDetails { address to; uint256 requestedAmount; }

    function permitTransferFrom(
        PermitTransferFrom memory permit,
        SignatureTransferDetails memory transferDetails,
        address owner,
        bytes memory signature
    ) external;
}

// ── Custom errors ──────────────────────────────────────────────────────────
error ZeroAddress();
error ZeroAmount();
error FeeTooHigh();
error ETHTransferFailed();
error DeadlineExpired();
error OracleSignatureInvalid();
error NonceAlreadyUsed();
error RecipientBlacklisted();
error TokenNotAllowed();

contract FeeRouterV3 is Ownable, ReentrancyGuard, EIP712 {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    // ── Immutables ─────────────────────────────────────────────────────────
    ISignatureTransfer public immutable PERMIT2;
    address            public immutable TREASURY_VAULT;

    // ── Storage ────────────────────────────────────────────────────────────
    address public oracleSigner;      // backend compliance signer
    uint16  public feeBps;            // 50 = 0.5%
    uint16  public constant MAX_FEE_BPS = 1_000;
    uint16  public constant BPS_DENOM   = 10_000;
    uint256 public constant SIGNATURE_VALIDITY = 120; // 2 minuti

    // ── Anti-replay ────────────────────────────────────────────────────────
    mapping(bytes32 => bool) private _usedNonces;

    // ── Token allowlist (owner può aggiungere/rimuovere) ───────────────────
    mapping(address => bool) public allowedTokens;

    // ── On-chain blacklist ─────────────────────────────────────────────────
    mapping(address => bool) public blacklisted;

    // ── EIP-712 ────────────────────────────────────────────────────────────
    bytes32 private constant _ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,address token,uint256 amount,bytes32 nonce,uint256 deadline)"
    );

    // ── Permit2 params struct ──────────────────────────────────────────────
    struct TransferParams {
        address token;
        uint256 amount;
        uint256 permit2Nonce;
        uint256 permit2Deadline;
        bytes   permit2Signature;
        address recipient;
        bytes32 paymentRef;
        bytes32 fiscalRef;
        bytes32 oracleNonce;
        uint256 oracleDeadline;
        bytes   oracleSignature;
    }

    // ── Events ─────────────────────────────────────────────────────────────
    event PaymentProcessed(
        address indexed sender,
        address indexed recipient,
        address indexed token,   // address(0) = ETH
        uint256 grossAmount,
        uint256 netAmount,
        uint256 feeAmount,
        bytes32 nonce,
        bytes32 paymentRef
    );
    event OracleSignerUpdated(address indexed old_, address indexed new_);
    event FeeBpsUpdated(uint16 old_, uint16 new_);
    event TokenAllowlistUpdated(address indexed token, bool allowed);
    event RecipientBlacklistUpdated(address indexed addr, bool status);

    // ── Constructor ────────────────────────────────────────────────────────
    constructor(
        address _permit2,
        address _treasury,
        address _oracleSigner,
        uint16  _feeBps,
        address _owner
    ) Ownable(_owner) EIP712("FeeRouterV3", "3") {
        if (_permit2       == address(0)) revert ZeroAddress();
        if (_treasury      == address(0)) revert ZeroAddress();
        if (_oracleSigner  == address(0)) revert ZeroAddress();
        if (_feeBps > MAX_FEE_BPS)        revert FeeTooHigh();

        PERMIT2        = ISignatureTransfer(_permit2);
        TREASURY_VAULT = _treasury;
        oracleSigner   = _oracleSigner;
        feeBps         = _feeBps;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  1. transferWithOracle — ERC-20 standard + Oracle signature
    //     Flow: Oracle pre-approva → utente chiama questa funzione
    //     Firma Oracle garantisce AML check passato
    // ══════════════════════════════════════════════════════════════════════
    function transferWithOracle(
        address _token,
        uint256 _amount,
        address _recipient,
        bytes32 _nonce,
        uint256 _deadline,
        bytes calldata _oracleSignature
    ) external nonReentrant {
        // ── CHECKS ────────────────────────────────────────────────────────
        if (_token     == address(0)) revert ZeroAddress();
        if (_recipient == address(0)) revert ZeroAddress();
        if (_amount    == 0)          revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (!allowedTokens[_token])   revert TokenNotAllowed();
        if (blacklisted[_recipient])  revert RecipientBlacklisted();

        // Verifica firma Oracle EIP-712
        _verifyOracleSignature(
            msg.sender, _recipient, _token, _amount,
            _nonce, _deadline, _oracleSignature
        );

        // ── EFFECTS ───────────────────────────────────────────────────────
        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(_amount);

        // ── INTERACTIONS ──────────────────────────────────────────────────
        // Pull tokens dal sender (require approve standard prima)
        IERC20(_token).safeTransferFrom(msg.sender, address(this), _amount);
        IERC20(_token).safeTransfer(_recipient,    net);
        IERC20(_token).safeTransfer(TREASURY_VAULT, fee);

        emit PaymentProcessed(
            msg.sender, _recipient, _token,
            _amount, net, fee, _nonce, bytes32(0)
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  2. transferETHWithOracle — ETH nativo + Oracle signature
    // ══════════════════════════════════════════════════════════════════════
    function transferETHWithOracle(
        address _recipient,
        bytes32 _nonce,
        uint256 _deadline,
        bytes calldata _oracleSignature
    ) external payable nonReentrant {
        if (_recipient == address(0)) revert ZeroAddress();
        if (msg.value  == 0)          revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (blacklisted[_recipient])  revert RecipientBlacklisted();

        _verifyOracleSignature(
            msg.sender, _recipient, address(0), msg.value,
            _nonce, _deadline, _oracleSignature
        );

        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(msg.value);

        (bool ok1,) = _recipient.call{value: net}("");
        if (!ok1) revert ETHTransferFailed();

        (bool ok2,) = TREASURY_VAULT.call{value: fee}("");
        if (!ok2) revert ETHTransferFailed();

        emit PaymentProcessed(
            msg.sender, _recipient, address(0),
            msg.value, net, fee, _nonce, bytes32(0)
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  3. transferWithPermit2 — Permit2 + Oracle in 1 TX atomica
    //     Flow: Oracle pre-approva + Permit2 off-chain sign → 1 TX
    // ══════════════════════════════════════════════════════════════════════
    function transferWithPermit2(
        TransferParams calldata p,
        address sender
    ) external nonReentrant {
        if (p.recipient == address(0)) revert ZeroAddress();
        if (p.amount    == 0)          revert ZeroAmount();
        if (block.timestamp > p.permit2Deadline) revert DeadlineExpired();
        if (block.timestamp > p.oracleDeadline)  revert DeadlineExpired();
        if (!allowedTokens[p.token])  revert TokenNotAllowed();
        if (blacklisted[p.recipient]) revert RecipientBlacklisted();

        _verifyOracleSignature(
            sender, p.recipient, p.token, p.amount,
            p.oracleNonce, p.oracleDeadline, p.oracleSignature
        );

        _usedNonces[p.oracleNonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(p.amount);

        // Permit2: sender → questo contratto
        PERMIT2.permitTransferFrom(
            ISignatureTransfer.PermitTransferFrom({
                permitted: ISignatureTransfer.TokenPermissions({
                    token: p.token, amount: p.amount
                }),
                nonce:    p.permit2Nonce,
                deadline: p.permit2Deadline
            }),
            ISignatureTransfer.SignatureTransferDetails({
                to: address(this), requestedAmount: p.amount
            }),
            sender,
            p.permit2Signature
        );

        IERC20(p.token).safeTransfer(p.recipient,    net);
        IERC20(p.token).safeTransfer(TREASURY_VAULT, fee);

        emit PaymentProcessed(
            sender, p.recipient, p.token,
            p.amount, net, fee, p.oracleNonce, p.paymentRef
        );
    }

    // ── View helpers ───────────────────────────────────────────────────────
    function calcSplit(uint256 _amount)
        external view returns (uint256 net, uint256 fee)
    {
        return _calcSplit(_amount);
    }

    function isNonceUsed(bytes32 _nonce) external view returns (bool) {
        return _usedNonces[_nonce];
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // ── Owner functions ────────────────────────────────────────────────────
    function setOracleSigner(address _new) external onlyOwner {
        if (_new == address(0)) revert ZeroAddress();
        emit OracleSignerUpdated(oracleSigner, _new);
        oracleSigner = _new;
    }

    function setFeeBps(uint16 _new) external onlyOwner {
        if (_new > MAX_FEE_BPS) revert FeeTooHigh();
        emit FeeBpsUpdated(feeBps, _new);
        feeBps = _new;
    }

    function setTokenAllowed(address _token, bool _allowed) external onlyOwner {
        allowedTokens[_token] = _allowed;
        emit TokenAllowlistUpdated(_token, _allowed);
    }

    /// @notice Configura più token in una sola TX (gas saving al deploy)
    function setTokensAllowed(
        address[] calldata _tokens,
        bool[] calldata _statuses
    ) external onlyOwner {
        require(_tokens.length == _statuses.length, "length mismatch");
        for (uint256 i = 0; i < _tokens.length; i++) {
            allowedTokens[_tokens[i]] = _statuses[i];
            emit TokenAllowlistUpdated(_tokens[i], _statuses[i]);
        }
    }

    function setBlacklisted(address _addr, bool _status) external onlyOwner {
        blacklisted[_addr] = _status;
        emit RecipientBlacklistUpdated(_addr, _status);
    }

    // ── Internal ───────────────────────────────────────────────────────────
    function _calcSplit(uint256 _amount)
        internal view returns (uint256 net, uint256 fee)
    {
        unchecked {
            fee = (_amount * feeBps) / BPS_DENOM;
            net = _amount - fee;
        }
    }

    function _verifyOracleSignature(
        address sender,
        address recipient,
        address token,
        uint256 amount,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata signature
    ) internal view {
        if (_usedNonces[nonce]) revert NonceAlreadyUsed();

        bytes32 structHash = keccak256(abi.encode(
            _ORACLE_TYPEHASH,
            sender, recipient, token, amount, nonce, deadline
        ));
        bytes32 digest = _hashTypedDataV4(structHash);

        address recovered = digest.recover(signature);
        if (recovered != oracleSigner) revert OracleSignatureInvalid();
    }

    receive()  external payable { revert("Usa transferETHWithOracle"); }
    fallback() external payable { revert("Funzione sconosciuta"); }
}
