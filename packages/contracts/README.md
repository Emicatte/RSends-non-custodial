# RSends Contracts

Foundry project for the non-custodial payment routers. Three production
contracts (Solidity `^0.8.24`, OpenZeppelin v5):

- [`src/RSendsRouterV2.sol`](src/RSendsRouterV2.sol) — **the mainnet design**:
  fee-less, **ownerless** single-merchant router (payer → merchant only, one
  transfer per payment, `ReentrancyGuard` and nothing else). Design decisions
  and their consequences: [`AUDIT_HANDOFF_ROUTERV2.md`](AUDIT_HANDOFF_ROUTERV2.md).
- [`src/RSendsRouter.sol`](src/RSendsRouter.sol) — the v1 testnet router
  (`Ownable2Step + Pausable + ReentrancyGuard`): on-chain flat fee, deployed
  and immutable on Base Sepolia.
- [`src/RSendsSplitRouter.sol`](src/RSendsSplitRouter.sol) — ownerless,
  fee-less N-way splitter (all-or-nothing, payer → recipients direct).

## What the routers do — and can't do

**RSendsRouterV2 (mainnet design):** a payment is **one direct transfer** —
payer → merchant, for exactly `amount`. No fee leg, no fee state, no fee
events; no owner, pause, or whitelist (no privileged role exists). The
contract never holds a balance and has no withdrawal, sweep, or rescue path.
Functions: `pay(invoiceId, merchant, token, amount)`,
`payWithPermit(…, deadline, v, r, s)`, `payNative(invoiceId, merchant,
amount)`; event `PaymentMade(invoiceId, merchant, payer, token, amount,
blockTimestamp)` (6 args — no fee word).

**RSendsRouter (v1, testnet):** a payment is **two direct transfers in one
transaction**: payer → merchant for the full amount, payer → `feeCollector`
for a flat fee. The contract never holds a balance and has no withdrawal,
sweep, or rescue path for user funds. The owner can configure per-token fees,
change the fee collector, and `pause()`/`unpause()` — it **cannot** move,
retain, or redirect merchant money.

| Function | Purpose |
|---|---|
| `quoteFee(token, amount)` | view — the exact fee the chain will charge (what the checkout displays) |
| `pay(invoiceId, merchant, token, amount, maxFee)` | ERC-20 payment; reverts if the quoted fee exceeds the payer's `maxFee` (no fee-config front-running) |
| `payWithPermit(...)` | same, attempting an EIP-2612 permit first — `try/catch` fallback covers non-conforming tokens (USDT, DAI) |
| `payNative(invoiceId, merchant, amount, maxFee)` | native ETH payment with `msg.value` validation |

Emits `PaymentMade(invoiceId, merchant, payer, token, amount, fee,
blockTimestamp)` — the event the backend indexer settles payment intents
against. Config events: `FeeConfigSet`, `FeeCollectorSet`.

## Fee model (v1/testnet only)

**RSendsRouterV2 has no fee model** — nothing below applies to it; pricing is
an off-chain subscription. The v1 testnet fee is flat and EUR-denominated per
token — never a percentage, no price oracle:
`fee = baseFee + (amount >= threshold ? surcharge : 0)`. Currently **€0.60**
below €1,000 and **€3.00** at or above. Native ETH is feeless (no oracle for a
EUR peg).

The single source of truth is
[`services/backend/app/token_registry.json`](../../services/backend/app/token_registry.json)
(smallest-unit encodings per token/decimals), shared with the backend and the
frontend. `foundry.toml` grants read-only `fs_permissions` on that file so
[`script/SetFeeConfig.s.sol`](script/SetFeeConfig.s.sol) can drive the on-chain
config from it.

## Layout

| Path | Contents |
|---|---|
| `src/RSendsRouterV2.sol` | the fee-less, ownerless mainnet router (see `AUDIT_HANDOFF_ROUTERV2.md`) |
| `src/RSendsRouter.sol` | the v1 testnet router (on-chain flat fee, owner-configured) |
| `src/RSendsSplitRouter.sol` | ownerless, fee-less N-way splitter |
| `test/RSendsRouterV2.t.sol` | 23 tests: single-transfer conservation fuzz, no-owner negatives (every v1 selector must revert), no-custody negatives, permit trio, FoT documented-not-gated, event-topic literal pin |
| `test/RSendsRouter.t.sol` | 34 tests: fee math, maxFee guard, permit fallback, pause, ownership; mocks incl. `MockERC20Permit`, USDT-style no-return, fee-on-transfer |
| `test/RSendsSplitRouter.t.sol` | 23 tests: split math/conservation, atomicity, permit, reentrancy |
| `test/SetFeeConfig.t.sol` | registry ↔ on-chain config integration (v1 only) |
| `script/DeployRouterV2.s.sol` | no-args v2 deploy (nothing to configure after) |
| `script/DeploySplitRouter.s.sol` | no-args split-router deploy |
| `script/SetFeeConfig.s.sol` | **v1 only** — wires per-chain token policy from the registry; asserts on-chain `symbol()`/`decimals()` before whitelisting; signs via Foundry keystore (`--account`), never a raw key. Never point it at a v2 deployment |
| `script/E2EDeploy.s.sol` | local-Anvil fixture (v1 + v2 + mock tokens) for the repo-root `make e2e-anvil` money-path E2E |
| `archive/` | **quarantined legacy custodial contracts** (FeeRouter lineage, CCIP, forwarders) — not compiled, not deployed, not product; see [`archive/README.md`](archive/README.md) |
| `DEPRECATED.md` | audit findings on the deprecated FeeRouterV3 (historical record) |

## Build & test

```bash
forge build
forge test
```

Full on-chain money-path E2E (deploy on Anvil, run the backend indexer, pay via
both the permit and approve paths) from the repo root: `make e2e-anvil`.

`foundry.toml`: optimizer on (200 runs), `via_ir = true`.

## Deploy

**RSendsRouterV2 (mainnet, operator-only):** `forge script
script/DeployRouterV2.s.sol:DeployRouterV2 --rpc-url <chain> --account
<keystore> --broadcast` — no constructor args, no post-deploy config; record
the address in `RSENDS_ROUTER_V2_ADDRESSES_JSON`. **No mainnet deployment
exists yet**; the artifact ships audit-ready for the RPagos review first.

### v1 (Base Sepolia — testnet)

There is intentionally **no testnet deploy script**; deploy directly with
`forge create` using a Foundry keystore (`cast wallet import` — the private key
never appears in env, files, or shell history). Constructor:
`RSendsRouter(address initialOwner, address initialFeeCollector)`. Then run
`SetFeeConfig.s.sol` **as the owner** to whitelist tokens from the registry.

The full step-by-step (keystore setup, verification, wiring the address into
backend and frontend env) lives in the repo-root
[`DEPLOY_RUNBOOK.md`](../../DEPLOY_RUNBOOK.md), Part 1.

### Deployed reference (Base Sepolia — testnet)

| | |
|---|---|
| Router | [`0x2Ec353815F2Cd382628d0D399F8d80959C1758CA`](https://sepolia.basescan.org/address/0x2Ec353815F2Cd382628d0D399F8d80959C1758CA) |
| Deploy block | `43196381` — also the `INDEXER_START_BLOCKS_JSON` backfill safety-net value |

Verified on-chain (`eth_getCode` returns no code at block 43196380 and the
router bytecode at 43196381), targeted by the `SetFeeConfig` broadcast under
`broadcast/SetFeeConfig.s.sol/84532/`, and pinned by the frontend test
`apps/web/app/__tests__/pay/payTokens.test.ts`. Testnet only — there is no
mainnet deployment of this contract.

## Dependencies

- OpenZeppelin Contracts v5 (`SafeERC20`, `IERC20Permit`, `ReentrancyGuard`,
  `Pausable`, `Ownable2Step`)
- Foundry (forge, cast, anvil)
