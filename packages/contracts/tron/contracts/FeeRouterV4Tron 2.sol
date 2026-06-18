// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * FeeRouterV4Tron.sol — Tron Network adaptation
 *
 * Changes from EVM FeeRouterV4:
 *   1. No Permit2 (not deployed on Tron)
 *   2. SunSwap V2 router (Uniswap V2 fork) instead of Uniswap V3
 *   3. WTRX instead of WETH
 *   4. Everything else identical: Oracle EIP-712, fee split, token allowlist
 *
 * SunSwap V2 Router: TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax
 * WTRX: TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR
 */

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

// SunSwap V2 — fork di Uniswap V2 (path-based routing)
interface ISunSwapRouter {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);

    function swapExactETHForTokens(
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external payable returns (uint256[] memory amounts);

    function getAmountsOut(
        uint256 amountIn,
        address[] calldata path
    ) external view returns (uint256[] memory amounts);
}

interface IWTRX {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function approve(address spender, uint256 amount) external returns (bool);
}

error ZeroAddress();
error ZeroAmount();
error FeeTooHigh();
error TRXTransferFailed();
error DeadlineExpired();
error OracleSignatureInvalid();
error NonceAlreadyUsed();
error TokenNotAllowed();
error RecipientBlacklisted();
error SlippageExceeded(uint256 received, uint256 minimum);
error InsufficientLiquidity();
error SameToken();
error MEVGuard();

contract FeeRouterV4Tron is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    // ── Immutables ──
    address         public immutable TREASURY_VAULT;
    ISunSwapRouter  public immutable SWAP_ROUTER;
    IWTRX           public immutable WTRX;

    // ── Storage ──
    address public oracleSigner;
    uint16  public feeBps;
    uint16  public constant MAX_FEE_BPS = 1_000;
    uint16  public constant BPS_DENOM   = 10_000;

    mapping(bytes32 => bool)  private _usedNonces;
    mapping(address => bool)  public  allowedTokens;
    mapping(address => bool)  public  blacklisted;

    // ── EIP-712 (identico a EVM) ──
    bytes32 private immutable _DOMAIN_SEPARATOR;

    bytes32 private constant _ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,"
        "address tokenIn,address tokenOut,uint256 amountIn,"
        "bytes32 nonce,uint256 deadline)"
    );

    // ── Events ──
    event PaymentProcessed(
        address indexed sender, address indexed recipient, address indexed tokenOut,
        uint256 grossOut, uint256 netOut, uint256 feeOut, bytes32 nonce, bool swapped
    );
    event SwapExecuted(address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);
    event OracleSignerUpdated(address old_, address new_);
    event FeeBpsUpdated(uint16 old_, uint16 new_);
    event TokenAllowlistUpdated(address token, bool allowed);

    // ── Constructor (6 params — no Permit2) ──
    constructor(
        address _treasury,
        address _oracleSigner,
        address _swapRouter,
        address _wtrx,
        uint16  _feeBps,
        address _owner
    ) Ownable(_owner) {
        if (_treasury     == address(0)) revert ZeroAddress();
        if (_oracleSigner == address(0)) revert ZeroAddress();
        if (_swapRouter   == address(0)) revert ZeroAddress();
        if (_wtrx         == address(0)) revert ZeroAddress();
        if (_feeBps > MAX_FEE_BPS)       revert FeeTooHigh();

        TREASURY_VAULT = _treasury;
        SWAP_ROUTER    = ISunSwapRouter(_swapRouter);
        WTRX           = IWTRX(_wtrx);
        oracleSigner   = _oracleSigner;
        feeBps         = _feeBps;

        _DOMAIN_SEPARATOR = keccak256(abi.encode(
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
            keccak256(bytes("FeeRouterV4")),
            keccak256(bytes("4")),
            block.chainid,
            address(this)
        ));
    }

    // ═══ 1. swapAndSend — SunSwap V2 path-based swap + fee split ═══
    function swapAndSend(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata oracleSignature
    ) external nonReentrant {
        if (tokenIn == address(0) || tokenOut == address(0) || recipient == address(0)) revert ZeroAddress();
        if (amountIn == 0)       revert ZeroAmount();
        if (minAmountOut == 0)   revert MEVGuard();
        if (tokenIn == tokenOut) revert SameToken();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenIn])    revert TokenNotAllowed();
        if (!allowedTokens[tokenOut])   revert TokenNotAllowed();
        if (blacklisted[recipient])     revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        uint256 amountOut = _swapV2(tokenIn, tokenOut, amountIn, minAmountOut, deadline);
        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        (uint256 net, uint256 fee) = _calcSplit(amountOut);
        IERC20(tokenOut).safeTransfer(recipient, net);
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        emit SwapExecuted(tokenIn, tokenOut, amountIn, amountOut);
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, net, fee, nonce, true);
    }

    // ═══ 2. swapTRXAndSend — TRX nativo → token swap + send ═══
    function swapTRXAndSend(
        address tokenOut,
        uint256 minAmountOut,
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata oracleSignature
    ) external payable nonReentrant {
        if (tokenOut == address(0) || recipient == address(0)) revert ZeroAddress();
        if (msg.value == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenOut])   revert TokenNotAllowed();
        if (blacklisted[recipient])     revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, address(0), tokenOut, msg.value, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        // SunSwap V2: usa swapExactETHForTokens (TRX nativo → token)
        address[] memory path = new address[](2);
        path[0] = address(WTRX);
        path[1] = tokenOut;

        uint256[] memory amounts;
        try SWAP_ROUTER.swapExactETHForTokens{value: msg.value}(
            minAmountOut, path, address(this), deadline
        ) returns (uint256[] memory _amounts) {
            amounts = _amounts;
        } catch {
            revert InsufficientLiquidity();
        }

        uint256 amountOut = amounts[amounts.length - 1];
        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        (uint256 net, uint256 fee) = _calcSplit(amountOut);
        IERC20(tokenOut).safeTransfer(recipient, net);
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        emit SwapExecuted(address(0), tokenOut, msg.value, amountOut);
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, net, fee, nonce, true);
    }

    // ═══ 3. transferWithOracle — TRC-20 direct (identico a EVM) ═══
    function transferWithOracle(
        address _token, uint256 _amount, address _recipient,
        bytes32 _nonce, uint256 _deadline, bytes calldata _oracleSignature
    ) external nonReentrant {
        if (_token == address(0) || _recipient == address(0)) revert ZeroAddress();
        if (_amount == 0) revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (!allowedTokens[_token])      revert TokenNotAllowed();
        if (blacklisted[_recipient])     revert RecipientBlacklisted();

        _verifyOracle(msg.sender, _recipient, _token, _token, _amount, _nonce, _deadline, _oracleSignature);
        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(_amount);
        IERC20(_token).safeTransferFrom(msg.sender, _recipient, net);
        IERC20(_token).safeTransferFrom(msg.sender, TREASURY_VAULT, fee);

        emit PaymentProcessed(msg.sender, _recipient, _token, _amount, net, fee, _nonce, false);
    }

    // ═══ 4. transferTRXWithOracle — TRX nativo direct ═══
    function transferTRXWithOracle(
        address _recipient, bytes32 _nonce, uint256 _deadline,
        bytes calldata _oracleSignature
    ) external payable nonReentrant {
        if (_recipient == address(0)) revert ZeroAddress();
        if (msg.value == 0) revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (blacklisted[_recipient])     revert RecipientBlacklisted();

        _verifyOracle(msg.sender, _recipient, address(0), address(0), msg.value, _nonce, _deadline, _oracleSignature);
        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(msg.value);
        (bool ok1,) = _recipient.call{value: net}("");
        if (!ok1) revert TRXTransferFailed();
        (bool ok2,) = TREASURY_VAULT.call{value: fee}("");
        if (!ok2) revert TRXTransferFailed();

        emit PaymentProcessed(msg.sender, _recipient, address(0), msg.value, net, fee, _nonce, false);
    }

    // ── Views ──
    function calcSplit(uint256 _amount) external view returns (uint256 net, uint256 fee) { return _calcSplit(_amount); }
    function isNonceUsed(bytes32 _nonce) external view returns (bool) { return _usedNonces[_nonce]; }
    function domainSeparator() external view returns (bytes32) { return _DOMAIN_SEPARATOR; }

    // ── Owner functions (identiche a EVM) ──
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
    function setTokensAllowed(address[] calldata _tokens, bool[] calldata _statuses) external onlyOwner {
        require(_tokens.length == _statuses.length, "length mismatch");
        for (uint256 i = 0; i < _tokens.length; i++) {
            allowedTokens[_tokens[i]] = _statuses[i];
            emit TokenAllowlistUpdated(_tokens[i], _statuses[i]);
        }
    }
    function setBlacklisted(address _addr, bool _status) external onlyOwner { blacklisted[_addr] = _status; }

    // ── Internal ──
    function _calcSplit(uint256 _amount) internal view returns (uint256 net, uint256 fee) {
        unchecked { fee = (_amount * feeBps) / BPS_DENOM; net = _amount - fee; }
    }

    function _swapV2(
        address tokenIn, address tokenOut,
        uint256 amountIn, uint256 amountOutMin, uint256 deadline
    ) internal returns (uint256) {
        IERC20(tokenIn).forceApprove(address(SWAP_ROUTER), amountIn);

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;

        uint256[] memory amounts;
        try SWAP_ROUTER.swapExactTokensForTokens(
            amountIn, amountOutMin, path, address(this), deadline
        ) returns (uint256[] memory _amounts) {
            amounts = _amounts;
        } catch {
            revert InsufficientLiquidity();
        }

        IERC20(tokenIn).forceApprove(address(SWAP_ROUTER), 0);
        return amounts[amounts.length - 1];
    }

    function _verifyOracle(
        address sender, address recipient, address tokenIn, address tokenOut,
        uint256 amountIn, bytes32 nonce, uint256 deadline, bytes calldata signature
    ) internal view {
        if (_usedNonces[nonce]) revert NonceAlreadyUsed();
        bytes32 structHash = keccak256(abi.encode(
            _ORACLE_TYPEHASH, sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", _DOMAIN_SEPARATOR, structHash));
        if (digest.recover(signature) != oracleSigner) revert OracleSignatureInvalid();
    }

    receive() external payable {}
    fallback() external payable { revert("Use exposed functions"); }
}
