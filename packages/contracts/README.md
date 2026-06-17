# RSend Smart Contracts

Solidity contracts for the RSend payment infrastructure. Built with Foundry.

## Contracts

### Core

| Contract | Description |
|---|---|
| `FeeRouterV4.sol` | Swap-and-forward router with Oracle EIP-712 signatures, Permit2, Uniswap V3 integration, 0.5% protocol fee |
| `RSendBatchDistributor.sol` | Gas-optimized batch distribution for ETH and ERC-20 tokens |
| `RSendForwarder.sol` | Deterministic per-user forwarding contracts with percentage splits |

### Cross-Chain (Chainlink CCIP)

| Contract | Description |
|---|---|
| `RSendCCIPSender.sol` | Cross-chain sender: bridge tokens via CCIP, or atomic swap (Uniswap V3) + bridge in 1 TX |
| `RSendCCIPReceiver.sol` | Cross-chain receiver: validates CCIP messages, forwards tokens to final recipient |
| `RSendCCIPSenderV2.sol` | V1 + explicit 200k gas limit in CCIP `extraArgs` (no reliance on Chainlink defaults) |
| `RSendCCIPReceiverV2.sol` | V1 + zero-recipient check after `abi.decode` to prevent token burns |
| `RSendForwarderV2.sol` | Hardened per-user forwarder (ReentrancyGuard + Ownable) |

### Router Evolution (FeeRouter line)

`FeeRouterV4` is the production router on Base. Later revisions are kept in `src/`
for staged rollout (see [`../ops/README.md`](../ops/README.md) for the live `setOracleSigner(s)` migration path):

| Version | Change |
|---|---|
| `FeeRouterV4` | Swap-and-forward + single Oracle EIP-712 signer + Permit2 + Uniswap V3, 0.5% fee (**live**) |
| `FeeRouterV4_1` | Adds owner-only `emergencyWithdrawETH/Token()` rescue |
| `FeeRouterV5` | Replaces single signer with **threshold-of-N multi-sig oracle** (`bytes[]` signatures) + emergency rescue |
| `FeeRouterV6` | **Flat fee model**: `feeBps`/`_calcSplit` removed — recipient receives the full token amount (fee charged out-of-band) |

Earlier `FeeRouter.sol` / `FeeRouterV3.sol` and `Counter.sol` are legacy/reference and not deployed.

## RSendCCIPSender Features

- **`sendCrossChain()`** — Bridge same token cross-chain (e.g., USDC Base -> USDC Arbitrum)
- **`swapAndBridge()`** — ERC20 swap via Uniswap V3 + CCIP bridge in 1 atomic TX
- **`swapETHAndBridge()`** — Native ETH -> wrap -> swap -> bridge in 1 atomic TX
- **`estimateFee()`** / **`estimateSwapAndBridgeFee()`** — On-chain CCIP fee estimation
- 0.5% RSend fee on bridged amount (configurable, max 10%)
- Anti-MEV: `minAmountOut` slippage protection required
- Token allowlist + recipient blacklist
- CCIP fee paid in native ETH, excess refunded to sender
- ReentrancyGuard on all external functions

## Supported Chains

| Chain | ID | CCIP Router | Uniswap SwapRouter |
|---|---|---|---|
| Base | 8453 | `0x881e3A65...` | `0x2626664c...` (SwapRouter02) |
| Ethereum | 1 | `0x80226fc0...` | `0x68b34658...` |
| Arbitrum | 42161 | `0x141fa059...` | `0x68b34658...` |
| Optimism | 10 | `0x3206695C...` | `0x68b34658...` |
| Polygon | 137 | `0x849c5ED5...` | `0x68b34658...` |
| BNB | 56 | `0x34B03Cb9...` | `0xB971eF87...` (PancakeSwap V3) |
| Avalanche | 43114 | `0xF4c7E640...` | `0xbb00FF08...` (Trader Joe V3) |

## Deployed Addresses

### Base Mainnet (Production)

| Contract | Address |
|---|---|
| FeeRouterV4 | `0x81d78BDD917D5A43a9E424B905407495b8f2c0f4` |
| RSendCCIPSender | *Pending deploy* |
| RSendCCIPReceiver | *Pending deploy* |

### Key Addresses

| Role | Address |
|---|---|
| Owner/Deployer | `0x0e056Ce14D1D56f799588f4760E5C39d47f14B82` |
| Treasury | `0x744Ad424bd3BC24838cF8201D1611d7cC828F9b9` |
| Oracle Signer | `0x50b593f57A3FE580096216A1cf8ba3aB070f4b85` |

## Build & Test

```bash
forge install OpenZeppelin/openzeppelin-contracts --no-git
forge build
forge test
```

## Deploy

### FeeRouterV4

```bash
export PRIVATE_KEY=0x...
forge script script/RedeployBaseSwapFix.s.sol:RedeployBaseSwapFix \
  --rpc-url https://mainnet.base.org --broadcast --verify
```

### CCIP (Sender + Receiver)

```bash
export PRIVATE_KEY=0x...
forge script script/DeployCCIP.s.sol:DeployCCIP \
  --rpc-url <RPC_URL> --broadcast --verify
```

Deploy on each chain, then link senders and receivers:

```bash
# On source chain: set receiver for destination
cast send <SENDER_ADDRESS> 'setReceiver(uint64,address)' <DEST_CHAIN_SELECTOR> <RECEIVER_ADDRESS>

# On destination chain: allow sender from source
cast send <RECEIVER_ADDRESS> 'setAllowedSender(uint64,address,bool)' <SOURCE_CHAIN_SELECTOR> <SENDER_ADDRESS> true

# Enable tokens on sender
cast send <SENDER_ADDRESS> 'setTokenAllowed(address,bool)' <TOKEN_ADDRESS> true
```

## Dependencies

- OpenZeppelin Contracts v5 (Ownable, IERC20, SafeERC20, ReentrancyGuard)
- Chainlink CCIP (IRouterClient interface)
- Uniswap V3 (ISwapRouter interface)
- Foundry (forge, cast, anvil)
