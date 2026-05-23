// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * FeeRouterV6.sol — Flat USDT Fee Model
 *
 * Changes from V5:
 *   - feeBps / _calcSplit removed: recipient now receives the full `amount`
 *     intact (zero deduction from the transaction token).
 *   - Flat 0.01 USDT fee (10_000 raw units, 6 decimals) pulled separately from
 *     msg.sender to TREASURY_VAULT via _collectFlatFee.
 *   - Dust skip for ERC20 paths: if amount < fixedFeeUSDT, the fee is silently
 *     skipped (sub-cent transactions are free).
 *   - ETH paths always charge the fee (no price oracle for ETH; B2B ETH
 *     payments are always above $0.01).
 *   - EIP-712 domain bumped to name="FeeRouterV6", version="6" so any V5
 *     pre-signed messages become invalid.
 *
 * Invariati da V5:
 *   Multi-signer oracle (threshold-of-N, ascending signer order)
 *   emergencyWithdrawETH / emergencyWithdrawToken
 *   allowedTokens / blacklisted / poolFeeOverride
 *   Uniswap V3 swap helpers (_swapExact, _pairKey, _getPoolFee)
 *
 * Deploy: Ethereum Mainnet (1) + Base (8453)
 * USDT Mainnet: 0xdAC17F958D2ee523a2206206994597C13D831ec7
 */

import {Ownable}          from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}           from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}        from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard}  from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ECDSA}            from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

// ── Uniswap V3 interfaces ──────────────────────────────────────────────────
interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24  fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params)
        external payable returns (uint256 amountOut);
}

interface IWETH {
    function deposit()  external payable;
    function withdraw(uint256 amount) external;
    function approve(address spender, uint256 amount) external returns (bool);
}

// ── Permit2 (ISignatureTransfer) ──────────────────────────────────────────
interface ISignatureTransfer {
    struct TokenPermissions     { address token; uint256 amount; }
    struct PermitTransferFrom   { TokenPermissions permitted; uint256 nonce; uint256 deadline; }
    struct SignatureTransferDetails { address to; uint256 requestedAmount; }
    function permitTransferFrom(
        PermitTransferFrom memory permit,
        SignatureTransferDetails memory transferDetails,
        address owner, bytes memory signature
    ) external;
}

// ── Custom errors ──────────────────────────────────────────────────────────
error ZeroAddress();
error ZeroAmount();
error ETHTransferFailed();
error DeadlineExpired();
error OracleSignatureInvalid();
error NonceAlreadyUsed();
error TokenNotAllowed();
error RecipientBlacklisted();
error SlippageExceeded(uint256 received, uint256 minimum);
error InsufficientLiquidity();
error SameToken();
error MEVGuard();
error InsufficientSignatures();
error SignersNotAscending();
error EmptySigners();
error ThresholdTooHigh();
error DuplicateSigner();
error USDTAllowanceInsufficient();

contract FeeRouterV6 is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    // ── Immutables ─────────────────────────────────────────────────────────
    ISignatureTransfer public immutable PERMIT2;
    address            public immutable TREASURY_VAULT;
    ISwapRouter        public immutable SWAP_ROUTER;
    IWETH              public immutable WETH;
    IERC20             public immutable USDT_TOKEN;

    // ── Storage ────────────────────────────────────────────────────────────
    uint256 public fixedFeeUSDT = 10_000;            // 0.01 USDT (6 decimals)
    uint8   public constant MAX_SIGNERS  = 10;

    // Pool fee tiers Uniswap V3
    uint24  public defaultPoolFee = 500;             // 0.05% — stablecoin pools
    uint24  public constant FEE_LOW  = 100;
    uint24  public constant FEE_MED  = 500;
    uint24  public constant FEE_HIGH = 3_000;

    // Multi-sig oracle
    address[] private _oracleSigners;
    mapping(address => bool) public isOracleSigner;
    uint8 public oracleThreshold;

    mapping(bytes32  => bool)    private _usedNonces;
    mapping(address  => bool)    public allowedTokens;
    mapping(address  => bool)    public blacklisted;
    mapping(bytes32  => uint24)  public poolFeeOverride;

    // ── EIP-712 ────────────────────────────────────────────────────────────
    bytes32 private immutable _DOMAIN_SEPARATOR;

    bytes32 private constant _ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,"
        "address tokenIn,address tokenOut,uint256 amountIn,"
        "bytes32 nonce,uint256 deadline)"
    );

    // ── Events ─────────────────────────────────────────────────────────────
    event PaymentProcessed(
        address indexed sender,
        address indexed recipient,
        address indexed tokenOut,
        uint256 grossOut,
        uint256 netOut,
        uint256 feeUSDT,
        bytes32 nonce,
        bool    swapped
    );

    event SwapExecuted(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint24  poolFee
    );

    event FlatFeeCollected(address indexed payer, uint256 feeUSDT, bytes32 nonce);
    event FixedFeeUpdated(uint256 old_, uint256 new_);

    event PoolFeeSet(address tokenA, address tokenB, uint24 fee);
    event OracleSignersUpdated(address[] signers, uint8 threshold);
    event TokenAllowlistUpdated(address token, bool allowed);
    event EmergencyETHWithdrawn(address indexed to, uint256 amount);
    event EmergencyTokenWithdrawn(address indexed token, address indexed to, uint256 amount);

    // ── Constructor ────────────────────────────────────────────────────────
    constructor(
        address   _permit2,
        address   _treasury,
        address[] memory _initialSigners,
        uint8     _threshold,
        address   _swapRouter,
        address   _weth,
        address   _usdt,
        address   _owner
    ) Ownable(_owner) {
        if (_permit2    == address(0)) revert ZeroAddress();
        if (_treasury   == address(0)) revert ZeroAddress();
        if (_swapRouter == address(0)) revert ZeroAddress();
        if (_weth       == address(0)) revert ZeroAddress();
        if (_usdt       == address(0)) revert ZeroAddress();

        PERMIT2        = ISignatureTransfer(_permit2);
        TREASURY_VAULT = _treasury;
        SWAP_ROUTER    = ISwapRouter(_swapRouter);
        WETH           = IWETH(_weth);
        USDT_TOKEN     = IERC20(_usdt);

        _setOracleSigners(_initialSigners, _threshold);

        _DOMAIN_SEPARATOR = keccak256(abi.encode(
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
            keccak256(bytes("FeeRouterV6")),
            keccak256(bytes("6")),
            block.chainid,
            address(this)
        ));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  1. swapAndSend
    // ══════════════════════════════════════════════════════════════════════
    function swapAndSend(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes[] calldata oracleSignatures
    ) external nonReentrant {
        if (tokenIn   == address(0)) revert ZeroAddress();
        if (tokenOut  == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (amountIn  == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (tokenIn   == tokenOut)   revert SameToken();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenIn])  revert TokenNotAllowed();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])   revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline, oracleSignatures);
        _usedNonces[nonce] = true;

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        uint256 amountOut = _swapExact(tokenIn, tokenOut, amountIn, minAmountOut);

        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        IERC20(tokenOut).safeTransfer(recipient, amountOut);

        uint256 feeCharged = _collectFlatFee(msg.sender, nonce, amountOut);

        emit SwapExecuted(tokenIn, tokenOut, amountIn, amountOut, _getPoolFee(tokenIn, tokenOut));
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, amountOut, feeCharged, nonce, true);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  2. swapETHAndSend
    // ══════════════════════════════════════════════════════════════════════
    function swapETHAndSend(
        address tokenOut,
        uint256 minAmountOut,
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes[] calldata oracleSignatures
    ) external payable nonReentrant {
        if (tokenOut  == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (msg.value == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])   revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, address(0), tokenOut, msg.value, nonce, deadline, oracleSignatures);
        _usedNonces[nonce] = true;

        WETH.deposit{value: msg.value}();

        uint256 amountOut = _swapExact(address(WETH), tokenOut, msg.value, minAmountOut);

        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        IERC20(tokenOut).safeTransfer(recipient, amountOut);

        // ETH path: bypass dust check (no price oracle for ETH).
        uint256 feeCharged = _collectFlatFee(msg.sender, nonce, type(uint256).max);

        emit SwapExecuted(address(0), tokenOut, msg.value, amountOut, _getPoolFee(address(WETH), tokenOut));
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, amountOut, feeCharged, nonce, true);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  3. transferWithOracle — ERC20 direct (full amount to recipient)
    // ══════════════════════════════════════════════════════════════════════
    function transferWithOracle(
        address _token,
        uint256 _amount,
        address _recipient,
        bytes32 _nonce,
        uint256 _deadline,
        bytes[] calldata _oracleSignatures
    ) external nonReentrant {
        if (_token     == address(0)) revert ZeroAddress();
        if (_recipient == address(0)) revert ZeroAddress();
        if (_amount    == 0)          revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (!allowedTokens[_token])   revert TokenNotAllowed();
        if (blacklisted[_recipient])  revert RecipientBlacklisted();

        _verifyOracle(msg.sender, _recipient, _token, _token, _amount, _nonce, _deadline, _oracleSignatures);
        _usedNonces[_nonce] = true;

        IERC20(_token).safeTransferFrom(msg.sender, _recipient, _amount);

        uint256 feeCharged = _collectFlatFee(msg.sender, _nonce, _amount);

        emit PaymentProcessed(msg.sender, _recipient, _token, _amount, _amount, feeCharged, _nonce, false);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  4. transferETHWithOracle — ETH direct (full msg.value to recipient)
    // ══════════════════════════════════════════════════════════════════════
    function transferETHWithOracle(
        address _recipient,
        bytes32 _nonce,
        uint256 _deadline,
        bytes[] calldata _oracleSignatures
    ) external payable nonReentrant {
        if (_recipient == address(0)) revert ZeroAddress();
        if (msg.value  == 0)          revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (blacklisted[_recipient])  revert RecipientBlacklisted();

        _verifyOracle(msg.sender, _recipient, address(0), address(0), msg.value, _nonce, _deadline, _oracleSignatures);
        _usedNonces[_nonce] = true;

        (bool ok,) = _recipient.call{value: msg.value}("");
        if (!ok) revert ETHTransferFailed();

        // ETH path: bypass dust check (no price oracle for ETH).
        uint256 feeCharged = _collectFlatFee(msg.sender, _nonce, type(uint256).max);

        emit PaymentProcessed(msg.sender, _recipient, address(0), msg.value, msg.value, feeCharged, _nonce, false);
    }

    // ── View helpers ───────────────────────────────────────────────────────
    function getFlatFee() external view returns (uint256) {
        return fixedFeeUSDT;
    }

    function isNonceUsed(bytes32 _nonce) external view returns (bool) {
        return _usedNonces[_nonce];
    }

    function domainSeparator() external view returns (bytes32) {
        return _DOMAIN_SEPARATOR;
    }

    function getOracleSigners() external view returns (address[] memory) {
        return _oracleSigners;
    }

    // ── Owner ──────────────────────────────────────────────────────────────
    function setOracleSigners(address[] calldata signers, uint8 threshold) external onlyOwner {
        _setOracleSigners(signers, threshold);
    }

    function setFixedFeeUSDT(uint256 _fee) external onlyOwner {
        emit FixedFeeUpdated(fixedFeeUSDT, _fee);
        fixedFeeUSDT = _fee;
    }

    function setTokenAllowed(address _token, bool _allowed) external onlyOwner {
        allowedTokens[_token] = _allowed;
        emit TokenAllowlistUpdated(_token, _allowed);
    }

    function setTokensAllowed(address[] calldata _tokens, bool[] calldata _statuses) external onlyOwner {
        require(_tokens.length == _statuses.length, "length mismatch");
        for (uint256 i = 0; i < _tokens.length; i++) {
            allowedTokens[_tokens[i]] = _statuses[i];
            emit TokenAllowlistUpdated(_tokens[i], _statuses[i]);
        }
    }

    function setBlacklisted(address _addr, bool _status) external onlyOwner {
        blacklisted[_addr] = _status;
    }

    function setDefaultPoolFee(uint24 _fee) external onlyOwner {
        require(_fee == 100 || _fee == 500 || _fee == 3000 || _fee == 10000, "Invalid fee");
        defaultPoolFee = _fee;
    }

    function setPoolFeeOverride(address tokenA, address tokenB, uint24 fee) external onlyOwner {
        require(fee == 100 || fee == 500 || fee == 3000 || fee == 10000, "Invalid fee");
        bytes32 key = _pairKey(tokenA, tokenB);
        poolFeeOverride[key] = fee;
        emit PoolFeeSet(tokenA, tokenB, fee);
    }

    // ── Emergency rescue ──────────────────────────────────────────────────

    function emergencyWithdrawETH(address payable to) external onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "No ETH to withdraw");
        require(to != address(0), "Zero recipient");
        (bool ok, ) = to.call{value: balance}("");
        require(ok, "ETH transfer failed");
        emit EmergencyETHWithdrawn(to, balance);
    }

    function emergencyWithdrawToken(address token, address to) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No token to withdraw");
        require(to != address(0), "Zero recipient");
        IERC20(token).safeTransfer(to, balance);
        emit EmergencyTokenWithdrawn(token, to, balance);
    }

    // ── Internal ───────────────────────────────────────────────────────────

    function _collectFlatFee(address payer, bytes32 nonce, uint256 amount)
        internal returns (uint256 feeCharged)
    {
        uint256 fee = fixedFeeUSDT;
        if (fee == 0)      return 0;   // fee disabled
        if (amount < fee)  return 0;   // dust skip (ETH path passes type(uint256).max)
        USDT_TOKEN.safeTransferFrom(payer, TREASURY_VAULT, fee);
        emit FlatFeeCollected(payer, fee, nonce);
        return fee;
    }

    function _pairKey(address a, address b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encodePacked(a, b)) : keccak256(abi.encodePacked(b, a));
    }

    function _getPoolFee(address a, address b) internal view returns (uint24) {
        uint24 override_ = poolFeeOverride[_pairKey(a, b)];
        return override_ != 0 ? override_ : defaultPoolFee;
    }

    function _swapExact(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOutMinimum
    ) internal returns (uint256 amountOut) {
        IERC20(tokenIn).forceApprove(address(SWAP_ROUTER), amountIn);

        try SWAP_ROUTER.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn:           tokenIn,
                tokenOut:          tokenOut,
                fee:               _getPoolFee(tokenIn, tokenOut),
                recipient:         address(this),
                amountIn:          amountIn,
                amountOutMinimum:  amountOutMinimum,
                sqrtPriceLimitX96: 0
            })
        ) returns (uint256 out) {
            amountOut = out;
        } catch {
            revert InsufficientLiquidity();
        }

        IERC20(tokenIn).forceApprove(address(SWAP_ROUTER), 0);
    }

    function _setOracleSigners(address[] memory signers, uint8 threshold) internal {
        if (signers.length == 0) revert EmptySigners();
        if (signers.length > MAX_SIGNERS) revert ThresholdTooHigh();
        if (threshold == 0 || threshold > signers.length) revert ThresholdTooHigh();

        // Clear old signers
        for (uint256 i = 0; i < _oracleSigners.length; i++) {
            isOracleSigner[_oracleSigners[i]] = false;
        }
        delete _oracleSigners;

        // Set new signers (must be sorted ascending, no duplicates, no zero)
        address lastAddr = address(0);
        for (uint256 i = 0; i < signers.length; i++) {
            if (signers[i] == address(0)) revert ZeroAddress();
            if (signers[i] <= lastAddr) revert DuplicateSigner();
            isOracleSigner[signers[i]] = true;
            _oracleSigners.push(signers[i]);
            lastAddr = signers[i];
        }

        oracleThreshold = threshold;
        emit OracleSignersUpdated(signers, threshold);
    }

    function _verifyOracle(
        address sender,
        address recipient,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        bytes32 nonce,
        uint256 deadline,
        bytes[] calldata signatures
    ) internal view {
        if (_usedNonces[nonce]) revert NonceAlreadyUsed();
        if (signatures.length < oracleThreshold) revert InsufficientSignatures();

        bytes32 structHash = keccak256(abi.encode(
            _ORACLE_TYPEHASH,
            sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", _DOMAIN_SEPARATOR, structHash));

        address lastSigner = address(0);
        for (uint256 i = 0; i < signatures.length; i++) {
            address recovered = digest.recover(signatures[i]);
            if (!isOracleSigner[recovered]) revert OracleSignatureInvalid();
            if (recovered <= lastSigner) revert SignersNotAscending();
            lastSigner = recovered;
        }
    }

    receive() external payable {}
    fallback() external payable { revert("Usa le funzioni esposte"); }
}
