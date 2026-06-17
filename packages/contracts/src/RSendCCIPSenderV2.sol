// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * RSendCCIPSenderV2 — Cross-chain token sender via Chainlink CCIP.
 *
 * Changes from V1:
 *   - Explicit gas limit in CCIP extraArgs (200k) instead of empty bytes.
 *     Empty extraArgs relies on Chainlink defaults which may be insufficient
 *     for RSendCCIPReceiver.ccipReceive logic.
 *
 * Deploy: 1 per chain sorgente (Base, Ethereum, Arbitrum, etc.)
 */

import {Ownable}         from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ── CCIP interfaces ───────────────────────────────────────────────────────
interface IRouterClient {
    struct EVM2AnyMessage {
        bytes             receiver;
        bytes             data;
        EVMTokenAmount[]  tokenAmounts;
        address           feeToken;      // address(0) = pay in native
        bytes             extraArgs;
    }

    struct EVMTokenAmount {
        address token;
        uint256 amount;
    }

    function getFee(
        uint64 destinationChainSelector,
        EVM2AnyMessage memory message
    ) external view returns (uint256 fee);

    function ccipSend(
        uint64 destinationChainSelector,
        EVM2AnyMessage calldata message
    ) external payable returns (bytes32 messageId);

    function isChainSupported(uint64 chainSelector) external view returns (bool);
}

// ── Uniswap V3 interfaces ────────────────────────────────────────────────
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
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function approve(address spender, uint256 amount) external returns (bool);
}

// ── Custom errors ─────────────────────────────────────────────────────────
error ZeroAddress();
error ZeroAmount();
error UnsupportedDestination();
error InsufficientFeeForCCIP();
error TokenNotAllowed();
error RecipientBlacklisted();
error SlippageExceeded(uint256 received, uint256 minimum);
error InsufficientLiquidity();
error SameToken();
error MEVGuard();

contract RSendCCIPSenderV2 is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ── Immutables ────────────────────────────────────────────────────────
    IRouterClient public immutable CCIP_ROUTER;
    address       public immutable TREASURY_VAULT;
    ISwapRouter   public immutable SWAP_ROUTER;
    IWETH         public immutable WETH;

    // ── CCIP gas limit ────────────────────────────────────────────────────
    // Chainlink CCIP EVMExtraArgsV1 tag: keccak256("CCIP EVMExtraArgsV1")[:4]
    bytes4 private constant CCIP_EVM_EXTRA_ARGS_V1_TAG = 0x97a657c9;

    // 200k gas covers RSendCCIPReceiver.ccipReceive (token loop + event).
    // Revisit if receiver logic grows.
    uint256 public constant CCIP_GAS_LIMIT = 200_000;

    // Pre-encoded extraArgs (tag + abi.encode(gasLimit)), set once in constructor
    bytes private _ccipExtraArgs;

    // ── Storage ───────────────────────────────────────────────────────────
    uint16 public feeBps = 50;             // 0.5%
    uint16 public constant BPS_DENOM = 10_000;
    uint16 public constant MAX_FEE_BPS = 1_000;
    uint24 public defaultPoolFee = 500;    // 0.05% Uniswap pool

    mapping(address => bool)   public allowedTokens;
    mapping(address => bool)   public blacklisted;
    mapping(uint64  => address) public receivers; // dest chain selector -> receiver contract

    // ── Events ────────────────────────────────────────────────────────────
    event CrossChainSent(
        bytes32 indexed messageId,
        uint64  indexed destinationChainSelector,
        address indexed sender,
        address recipient,
        address token,
        uint256 grossAmount,
        uint256 netAmount,
        uint256 fee,
        uint256 ccipFee
    );

    event CrossChainSwapAndBridge(
        bytes32 indexed messageId,
        uint64  indexed destinationChainSelector,
        address indexed sender,
        address recipient,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 netBridged,
        uint256 fee
    );

    event ReceiverSet(uint64 chainSelector, address receiver);
    event EmergencyETHWithdrawn(address indexed to, uint256 amount);
    event EmergencyTokenWithdrawn(address indexed token, address indexed to, uint256 amount);

    // ── Constructor ───────────────────────────────────────────────────────
    constructor(
        address _ccipRouter,
        address _treasury,
        address _swapRouter,
        address _weth,
        address _owner
    ) Ownable(_owner) {
        if (_ccipRouter  == address(0)) revert ZeroAddress();
        if (_treasury    == address(0)) revert ZeroAddress();
        if (_swapRouter  == address(0)) revert ZeroAddress();
        if (_weth        == address(0)) revert ZeroAddress();
        CCIP_ROUTER    = IRouterClient(_ccipRouter);
        TREASURY_VAULT = _treasury;
        SWAP_ROUTER    = ISwapRouter(_swapRouter);
        WETH           = IWETH(_weth);

        _ccipExtraArgs = abi.encodePacked(
            CCIP_EVM_EXTRA_ARGS_V1_TAG,
            abi.encode(CCIP_GAS_LIMIT)
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  sendCrossChain — Invia token cross-chain via CCIP
    // ══════════════════════════════════════════════════════════════════════
    function sendCrossChain(
        uint64  destinationChainSelector,
        address recipient,
        address token,
        uint256 amount
    ) external payable nonReentrant {
        if (recipient == address(0)) revert ZeroAddress();
        if (token     == address(0)) revert ZeroAddress();
        if (amount    == 0)          revert ZeroAmount();
        if (!allowedTokens[token])   revert TokenNotAllowed();
        if (blacklisted[recipient])  revert RecipientBlacklisted();

        address receiverOnDest = receivers[destinationChainSelector];
        if (receiverOnDest == address(0)) revert UnsupportedDestination();

        // ── Fee split ─────────────────────────────────────────────────────
        uint256 fee = (amount * feeBps) / BPS_DENOM;
        uint256 netAmount = amount - fee;

        // Pull token dal sender
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);

        // Fee -> treasury
        IERC20(token).safeTransfer(TREASURY_VAULT, fee);

        // Approva CCIP Router per il net amount
        IERC20(token).forceApprove(address(CCIP_ROUTER), netAmount);

        // Costruisci CCIP message
        IRouterClient.EVM2AnyMessage memory message = _buildMessage(
            receiverOnDest, recipient, token, netAmount
        );

        // Calcola CCIP fee
        uint256 ccipFee = CCIP_ROUTER.getFee(destinationChainSelector, message);
        if (msg.value < ccipFee) revert InsufficientFeeForCCIP();

        // Invia via CCIP
        bytes32 messageId = CCIP_ROUTER.ccipSend{value: ccipFee}(
            destinationChainSelector,
            message
        );

        // Refund ETH in eccesso
        if (msg.value > ccipFee) {
            (bool ok,) = msg.sender.call{value: msg.value - ccipFee}("");
            require(ok, "ETH refund failed");
        }

        // Reset approval
        IERC20(token).forceApprove(address(CCIP_ROUTER), 0);

        emit CrossChainSent(
            messageId, destinationChainSelector,
            msg.sender, recipient, token,
            amount, netAmount, fee, ccipFee
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  swapAndBridge — ERC20 swap + cross-chain in 1 TX
    // ══════════════════════════════════════════════════════════════════════
    function swapAndBridge(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        uint64  destinationChainSelector,
        address recipient
    ) external payable nonReentrant {
        if (tokenIn  == address(0)) revert ZeroAddress();
        if (tokenOut == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (amountIn == 0)           revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (tokenIn == tokenOut)     revert SameToken();
        if (!allowedTokens[tokenIn]) revert TokenNotAllowed();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])  revert RecipientBlacklisted();

        address receiverOnDest = receivers[destinationChainSelector];
        if (receiverOnDest == address(0)) revert UnsupportedDestination();

        // 1. Pull tokenIn
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        // 2. Swap via Uniswap V3
        uint256 amountOut = _swapExact(tokenIn, tokenOut, amountIn, minAmountOut);
        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        // 3. Fee split sul tokenOut
        uint256 fee = (amountOut * feeBps) / BPS_DENOM;
        uint256 netAmount = amountOut - fee;
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        // 4. Bridge via CCIP. M3: pass msg.value as the ETH budget so the refund
        // is scoped to THIS call's leftover (msg.value - ccipFee) and never the
        // whole contract balance (which would let a dust swap drain stranded ETH).
        bytes32 messageId = _sendViaCCIPWithValue(
            destinationChainSelector, receiverOnDest,
            recipient, tokenOut, netAmount, msg.value
        );

        emit CrossChainSwapAndBridge(
            messageId, destinationChainSelector,
            msg.sender, recipient,
            tokenIn, tokenOut,
            amountIn, amountOut, netAmount, fee
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  swapETHAndBridge — ETH nativo → token swap + cross-chain
    // ══════════════════════════════════════════════════════════════════════
    function swapETHAndBridge(
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        uint64  destinationChainSelector,
        address recipient
    ) external payable nonReentrant {
        if (tokenOut  == address(0)) revert ZeroAddress();
        if (recipient == address(0)) revert ZeroAddress();
        if (amountIn  == 0)          revert ZeroAmount();
        if (minAmountOut == 0)       revert MEVGuard();
        if (!allowedTokens[tokenOut]) revert TokenNotAllowed();
        if (blacklisted[recipient])  revert RecipientBlacklisted();
        require(msg.value > amountIn, "msg.value must cover amountIn + CCIP fee");

        address receiverOnDest = receivers[destinationChainSelector];
        if (receiverOnDest == address(0)) revert UnsupportedDestination();

        // 1. Wrap ETH → WETH
        WETH.deposit{value: amountIn}();

        // 2. Swap WETH → tokenOut via Uniswap V3
        uint256 amountOut = _swapExact(address(WETH), tokenOut, amountIn, minAmountOut);
        if (amountOut < minAmountOut) revert SlippageExceeded(amountOut, minAmountOut);

        // 3. Fee split
        uint256 fee = (amountOut * feeBps) / BPS_DENOM;
        uint256 netAmount = amountOut - fee;
        IERC20(tokenOut).safeTransfer(TREASURY_VAULT, fee);

        // 4. Bridge via CCIP (CCIP fee pagata dal ETH rimanente in msg.value)
        bytes32 messageId = _sendViaCCIPWithValue(
            destinationChainSelector, receiverOnDest,
            recipient, tokenOut, netAmount,
            msg.value - amountIn
        );

        emit CrossChainSwapAndBridge(
            messageId, destinationChainSelector,
            msg.sender, recipient,
            address(0), tokenOut,
            amountIn, amountOut, netAmount, fee
        );
    }

    // ── View: stima fee CCIP ──────────────────────────────────────────────
    function estimateFee(
        uint64  destinationChainSelector,
        address recipient,
        address token,
        uint256 netAmount
    ) external view returns (uint256 ccipFee) {
        address receiverOnDest = receivers[destinationChainSelector];
        if (receiverOnDest == address(0)) return 0;

        IRouterClient.EVM2AnyMessage memory message = _buildMessage(
            receiverOnDest, recipient, token, netAmount
        );

        return CCIP_ROUTER.getFee(destinationChainSelector, message);
    }

    // ── View: stima fee per swapAndBridge ─────────────────────────────────
    function estimateSwapAndBridgeFee(
        address tokenOut,
        uint256 netAmountOut,
        uint64  destinationChainSelector,
        address recipient
    ) external view returns (uint256 ccipFee) {
        address receiverOnDest = receivers[destinationChainSelector];
        if (receiverOnDest == address(0)) return 0;

        IRouterClient.EVM2AnyMessage memory message = _buildMessage(
            receiverOnDest, recipient, tokenOut, netAmountOut
        );

        return CCIP_ROUTER.getFee(destinationChainSelector, message);
    }

    // ── Owner ─────────────────────────────────────────────────────────────
    function setReceiver(uint64 chainSelector, address receiver) external onlyOwner {
        receivers[chainSelector] = receiver;
        emit ReceiverSet(chainSelector, receiver);
    }

    function setTokenAllowed(address token, bool allowed) external onlyOwner {
        allowedTokens[token] = allowed;
    }

    function setFeeBps(uint16 _new) external onlyOwner {
        require(_new <= MAX_FEE_BPS, "Fee too high");
        feeBps = _new;
    }

    function setBlacklisted(address addr, bool status) external onlyOwner {
        blacklisted[addr] = status;
    }

    function setDefaultPoolFee(uint24 _fee) external onlyOwner {
        require(_fee == 100 || _fee == 500 || _fee == 3000 || _fee == 10000, "Invalid fee");
        defaultPoolFee = _fee;
    }

    // ── Emergency rescue (M3) ─────────────────────────────────────────────
    // Recover ETH / tokens accidentally stranded in the contract. The router
    // refunds are now call-scoped, so nothing should accumulate — but a rescue
    // path is required since there was no withdraw function at all.
    function rescueETH(address payable to) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        uint256 balance = address(this).balance;
        require(balance > 0, "No ETH to rescue");
        (bool ok, ) = to.call{value: balance}("");
        require(ok, "ETH rescue failed");
        emit EmergencyETHWithdrawn(to, balance);
    }

    function rescueToken(address token, address to) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No token to rescue");
        IERC20(token).safeTransfer(to, balance);
        emit EmergencyTokenWithdrawn(token, to, balance);
    }

    // ── Internal: build CCIP message ──────────────────────────────────────
    function _buildMessage(
        address receiverOnDest,
        address recipient,
        address token,
        uint256 amount
    ) internal view returns (IRouterClient.EVM2AnyMessage memory) {
        IRouterClient.EVMTokenAmount[] memory tokenAmounts =
            new IRouterClient.EVMTokenAmount[](1);
        tokenAmounts[0] = IRouterClient.EVMTokenAmount({
            token: token,
            amount: amount
        });

        return IRouterClient.EVM2AnyMessage({
            receiver: abi.encode(receiverOnDest),
            data: abi.encode(recipient),
            tokenAmounts: tokenAmounts,
            feeToken: address(0),
            extraArgs: _ccipExtraArgs
        });
    }

    // ── Internal: Uniswap V3 swap ─────────────────────────────────────────
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
                fee:               defaultPoolFee,
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

    // ── Internal: manda via CCIP (fee pagata in ETH da msg.value) ─────────
    // ── Internal: variante con budget ETH specifico per CCIP ──────────────
    // (M3: the old _sendViaCCIP — which refunded address(this).balance and so
    // let a dust swap drain stranded ETH — was removed; both swapAndBridge and
    // swapETHAndBridge now use this call-scoped variant.)
    function _sendViaCCIPWithValue(
        uint64  destinationChainSelector,
        address receiverOnDest,
        address recipient,
        address token,
        uint256 amount,
        uint256 ethBudget
    ) internal returns (bytes32) {
        IERC20(token).forceApprove(address(CCIP_ROUTER), amount);

        IRouterClient.EVM2AnyMessage memory message = _buildMessage(
            receiverOnDest, recipient, token, amount
        );

        uint256 ccipFee = CCIP_ROUTER.getFee(destinationChainSelector, message);
        require(ethBudget >= ccipFee, "Insufficient ETH budget for CCIP fee");

        bytes32 messageId = CCIP_ROUTER.ccipSend{value: ccipFee}(
            destinationChainSelector, message
        );

        IERC20(token).forceApprove(address(CCIP_ROUTER), 0);

        // Refund
        uint256 refund = ethBudget - ccipFee;
        if (refund > 0) {
            (bool ok,) = msg.sender.call{value: refund}("");
            require(ok, "ETH refund failed");
        }

        return messageId;
    }

    // Per ricevere ETH refund da CCIP
    receive() external payable {}
}
