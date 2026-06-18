// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * FeeRouterV4.sol — Omni-chain Swap-and-Forward
 *
 * Nuove funzioni rispetto a V3:
 *   swapAndSend()     — swap ETH/ERC20 → tokenOut via Uniswap V3, poi split
 *   swapETHAndSend()  — helper payable per ETH → token
 *
 * Invariati da V3:
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

contract FeeRouterV4 is Ownable, ReentrancyGuard {
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

    // ── Constructor ────────────────────────────────────────────────────────
    constructor(
        address _permit2,
        address _treasury,
        address _oracleSigner,
        address _swapRouter,
        address _weth,
        uint16  _feeBps,
        address _owner
    ) Ownable(_owner) {
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

        _DOMAIN_SEPARATOR = keccak256(abi.encode(
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
            keccak256(bytes("FeeRouterV4")),
            keccak256(bytes("4")),
            block.chainid,
            address(this)
        ));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  1. swapAndSend — Uniswap V3 swap + fee split in 1 TX
    //
    //  Flow:
    //    1. Verifica Oracle signature (AML pre-approvato)
    //    2. Pull tokenIn dal sender tramite Permit2 o approve standard
    //    3. Swap tokenIn → tokenOut via Uniswap V3 exactInputSingle
    //    4. Slippage check: revert se output < minAmountOut
    //    5. Split atomico: 99.5% → recipient, 0.5% → treasury
    // ══════════════════════════════════════════════════════════════════════
    function swapAndSend(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,        // MEV guard — mai 0
        address recipient,
        bytes32 nonce,
        uint256 deadline,
        bytes calldata oracleSignature
    ) external nonReentrant {
        // ── CHECKS ────────────────────────────────────────────────────────
        if (tokenIn   == address(0)) revert ZeroAddress();
        if (tokenOut  == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (amountIn  == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();          // anti-MEV
        if (tokenIn   == tokenOut)   revert SameToken();
        if (block.timestamp > deadline) revert DeadlineExpired();
        if (!allowedTokens[tokenIn])  revert TokenNotAllowed();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])   revert RecipientBlacklisted();

        _verifyOracle(msg.sender, recipient, tokenIn, tokenOut, amountIn, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        // ── Pull tokenIn → questo contratto ───────────────────────────────
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        // ── Swap via Uniswap V3 ───────────────────────────────────────────
        uint256 amountOut = _swapExact(tokenIn, tokenOut, amountIn, minAmountOut);

        // ── Slippage check ────────────────────────────────────────────────
        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        // ── Split sul tokenOut ────────────────────────────────────────────
        (uint256 net, uint256 fee) = _calcSplit(amountOut);
        IERC20(tokenOut).safeTransfer(recipient,     net);
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        emit SwapExecuted(tokenIn, tokenOut, amountIn, amountOut, _getPoolFee(tokenIn, tokenOut));
        emit PaymentProcessed(msg.sender, recipient, tokenOut, amountOut, net, fee, nonce, true);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  2. swapETHAndSend — ETH → tokenOut swap + send
    //     Il sender manda ETH nativo, viene wrappato in WETH e swappato
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

        // Oracle verifica con address(0) = ETH come tokenIn
        _verifyOracle(msg.sender, recipient, address(0), tokenOut, msg.value, nonce, deadline, oracleSignature);
        _usedNonces[nonce] = true;

        // Wrappa ETH → WETH
        WETH.deposit{value: msg.value}();

        // Swap WETH → tokenOut
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
        return _DOMAIN_SEPARATOR;
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

    /// @notice Imposta pool fee per una coppia specifica (es. ETH/USDC = 500, cbBTC/ETH = 3000)
    function setPoolFeeOverride(address tokenA, address tokenB, uint24 fee) external onlyOwner {
        require(fee == 100 || fee == 500 || fee == 3000 || fee == 10000, "Invalid fee");
        bytes32 key = _pairKey(tokenA, tokenB);
        poolFeeOverride[key] = fee;
        emit PoolFeeSet(tokenA, tokenB, fee);
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
        // Approva SwapRouter
        IERC20(tokenIn).forceApprove(address(SWAP_ROUTER), amountIn);

        try SWAP_ROUTER.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn:           tokenIn,
                tokenOut:          tokenOut,
                fee:               _getPoolFee(tokenIn, tokenOut),
                recipient:         address(this),
                amountIn:          amountIn,
                amountOutMinimum:  amountOutMinimum,
                sqrtPriceLimitX96: 0  // no price limit, protetto da minAmountOut
            })
        ) returns (uint256 out) {
            amountOut = out;
        } catch {
            revert InsufficientLiquidity();
        }

        // Reset approvazione per sicurezza
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
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", _DOMAIN_SEPARATOR, structHash));
        address recovered = digest.recover(signature);
        if (recovered != oracleSigner) revert OracleSignatureInvalid();
    }

    receive() external payable {}
    fallback() external payable { revert("Usa le funzioni esposte"); }
}
