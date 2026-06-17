// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * FeeRouterV4_1.sol — Omni-chain Swap-and-Forward + Emergency Rescue
 *
 * Changes from V4:
 *   emergencyWithdrawETH()   — owner-only ETH rescue
 *   emergencyWithdrawToken() — owner-only ERC-20 rescue
 *
 * EIP-712 domain version bumped to "4.1" (invalidates pre-signed V4 messages).
 *
 * Invariati da V4:
 *   swapAndSend()            — Uniswap V3 swap + fee split in 1 TX
 *   swapETHAndSend()         — ETH → tokenOut swap + send
 *   transferWithOracle()     — ERC20 direct transfer + Oracle
 *   transferETHWithOracle()  — ETH direct transfer + Oracle
 *
 * Deploy: Ethereum Mainnet (1) + Base (8453)
 * Uniswap V3 SwapRouter02: 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45
 * WETH Mainnet:  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
 * WETH Base:     0x4200000000000000000000000000000000000006
 */

import {Ownable}          from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}           from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}        from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard}  from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ECDSA}            from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import {EIP712}           from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";

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
error FeeTooHigh();
error ETHTransferFailed();
error DeadlineExpired();
error OracleSignatureInvalid();
error NonceAlreadyUsed();
error TokenNotAllowed();
error RecipientBlacklisted();
error SlippageExceeded(uint256 received, uint256 minimum);
error InsufficientLiquidity();
error SameToken();
error MEVGuard();           // amountOutMinimum == 0

contract FeeRouterV4_1 is Ownable, ReentrancyGuard, EIP712 {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    // ── Immutables ─────────────────────────────────────────────────────────
    ISignatureTransfer public immutable PERMIT2;
    address            public immutable TREASURY_VAULT;
    ISwapRouter        public immutable SWAP_ROUTER;
    IWETH              public immutable WETH;

    // ── Storage ────────────────────────────────────────────────────────────
    address public oracleSigner;
    uint16  public feeBps;
    uint16  public constant MAX_FEE_BPS  = 1_000;  // 10%
    uint16  public constant BPS_DENOM    = 10_000;

    // Pool fee tiers Uniswap V3
    uint24  public defaultPoolFee = 500;            // 0.05% — stablecoin pools
    uint24  public constant FEE_LOW  = 100;
    uint24  public constant FEE_MED  = 500;
    uint24  public constant FEE_HIGH = 3_000;

    mapping(bytes32  => bool)    private _usedNonces;
    mapping(address  => bool)    public allowedTokens;
    mapping(address  => bool)    public blacklisted;
    // Override pool fee per coppia token (keccak(tokenA, tokenB) → fee)
    mapping(bytes32  => uint24)  public poolFeeOverride;

    // ── EIP-712 ────────────────────────────────────────────────────────────
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
        uint256 feeOut,
        bytes32 nonce,
        bool    swapped      // true se è avvenuto uno swap
    );

    event SwapExecuted(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint24  poolFee
    );

    event PoolFeeSet(address tokenA, address tokenB, uint24 fee);
    event OracleSignerUpdated(address old_, address new_);
    event FeeBpsUpdated(uint16 old_, uint16 new_);
    event TokenAllowlistUpdated(address token, bool allowed);
    event EmergencyETHWithdrawn(address indexed to, uint256 amount);
    event EmergencyTokenWithdrawn(address indexed token, address indexed to, uint256 amount);

    // ── Constructor ────────────────────────────────────────────────────────
    constructor(
        address _permit2,
        address _treasury,
        address _oracleSigner,
        address _swapRouter,
        address _weth,
        uint16  _feeBps,
        address _owner
    ) Ownable(_owner) EIP712("FeeRouterV4_1", "4.1") {
        if (_permit2      == address(0)) revert ZeroAddress();
        if (_treasury     == address(0)) revert ZeroAddress();
        if (_oracleSigner == address(0)) revert ZeroAddress();
        if (_swapRouter   == address(0)) revert ZeroAddress();
        if (_weth         == address(0)) revert ZeroAddress();
        if (_feeBps > MAX_FEE_BPS)       revert FeeTooHigh();

        PERMIT2       = ISignatureTransfer(_permit2);
        TREASURY_VAULT = _treasury;
        SWAP_ROUTER   = ISwapRouter(_swapRouter);
        WETH          = IWETH(_weth);
        oracleSigner  = _oracleSigner;
        feeBps        = _feeBps;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  1. swapAndSend — Uniswap V3 swap + fee split in 1 TX
    // ══════════════════════════════════════════════════════════════════════
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

        _verifyOracle(msg.sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        uint256 amountOut = _swapExact(tokenIn, tokenOut, amountIn, minAmountOut);

        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        (uint256 net, uint256 fee) = _calcSplit(amountOut);
        IERC20(tokenOut).safeTransfer(recipient,     net);
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        emit SwapExecuted(tokenIn, tokenOut, amountIn, amountOut, _getPoolFee(tokenIn, tokenOut));
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, net, fee, nonce, true);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  2. swapETHAndSend — ETH → tokenOut swap + send
    // ══════════════════════════════════════════════════════════════════════
    function swapETHAndSend(
        address tokenOut,
        uint256 minAmountOut,
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata oracleSignature
    ) external payable nonReentrant {
        if (tokenOut  == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (msg.value == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])   revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, address(0), tokenOut, msg.value, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        WETH.deposit{value: msg.value}();

        uint256 amountOut = _swapExact(address(WETH), tokenOut, msg.value, minAmountOut);

        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        (uint256 net, uint256 fee) = _calcSplit(amountOut);
        IERC20(tokenOut).safeTransfer(recipient,     net);
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        emit SwapExecuted(address(0), tokenOut, msg.value, amountOut, _getPoolFee(address(WETH), tokenOut));
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, net, fee, nonce, true);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  3. transferWithOracle — ERC20 direct (invariato da V3)
    // ══════════════════════════════════════════════════════════════════════
    function transferWithOracle(
        address _token,
        uint256 _amount,
        address _recipient,
        bytes32 _nonce,
        uint256 _deadline,
        bytes calldata _oracleSignature
    ) external nonReentrant {
        if (_token     == address(0)) revert ZeroAddress();
        if (_recipient == address(0)) revert ZeroAddress();
        if (_amount    == 0)          revert ZeroAmount();
        if (block.timestamp > _deadline) revert DeadlineExpired();
        if (!allowedTokens[_token])   revert TokenNotAllowed();
        if (blacklisted[_recipient])  revert RecipientBlacklisted();

        _verifyOracle(msg.sender, _recipient, _token, _token, _amount, _nonce, _deadline, _oracleSignature);
        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(_amount);
        IERC20(_token).safeTransferFrom(msg.sender, _recipient,     net);
        IERC20(_token).safeTransferFrom(msg.sender, TREASURY_VAULT, fee);

        emit PaymentProcessed(msg.sender, _recipient, _token, _amount, net, fee, _nonce, false);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  4. transferETHWithOracle — ETH direct (invariato da V3)
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

        _verifyOracle(msg.sender, _recipient, address(0), address(0), msg.value, _nonce, _deadline, _oracleSignature);
        _usedNonces[_nonce] = true;

        (uint256 net, uint256 fee) = _calcSplit(msg.value);
        (bool ok1,) = _recipient.call{value: net}("");
        if (!ok1) revert ETHTransferFailed();
        (bool ok2,) = TREASURY_VAULT.call{value: fee}("");
        if (!ok2) revert ETHTransferFailed();

        emit PaymentProcessed(msg.sender, _recipient, address(0), msg.value, net, fee, _nonce, false);
    }

    // ── View helpers ───────────────────────────────────────────────────────
    function calcSplit(uint256 _amount) external view returns (uint256 net, uint256 fee) {
        return _calcSplit(_amount);
    }

    function isNonceUsed(bytes32 _nonce) external view returns (bool) {
        return _usedNonces[_nonce];
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // ── Owner ──────────────────────────────────────────────────────────────
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

    /// @notice Recover ETH accidentally sent directly to the contract.
    function emergencyWithdrawETH(address payable to) external onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "No ETH to withdraw");
        require(to != address(0), "Zero recipient");
        (bool ok, ) = to.call{value: balance}("");
        require(ok, "ETH transfer failed");
        emit EmergencyETHWithdrawn(to, balance);
    }

    /// @notice Recover ERC-20 tokens stuck from failed swaps or accidental sends.
    function emergencyWithdrawToken(address token, address to) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No token to withdraw");
        require(to != address(0), "Zero recipient");
        IERC20(token).safeTransfer(to, balance);
        emit EmergencyTokenWithdrawn(token, to, balance);
    }

    // ── Internal ───────────────────────────────────────────────────────────
    function _calcSplit(uint256 _amount) internal view returns (uint256 net, uint256 fee) {
        unchecked {
            fee = (_amount * feeBps) / BPS_DENOM;
            net = _amount - fee;
        }
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

    function _verifyOracle(
        address sender,
        address recipient,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata signature
    ) internal view {
        if (_usedNonces[nonce]) revert NonceAlreadyUsed();

        bytes32 structHash = keccak256(abi.encode(
            _ORACLE_TYPEHASH,
            sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline
        ));
        bytes32 digest = _hashTypedDataV4(structHash);
        address recovered = digest.recover(signature);
        if (recovered != oracleSigner) revert OracleSignatureInvalid();
    }

    receive() external payable {}
    fallback() external payable { revert("Usa le funzioni esposte"); }
}
