# RSends Contracts — `RSendsRouter.sol`

Foundry project for the non-custodial payment router. One production contract:
[`src/RSendsRouter.sol`](src/RSendsRouter.sol) (Solidity `^0.8.24`,
`Ownable2Step + Pausable + ReentrancyGuard`, OpenZeppelin v5).

## What the router does — and can't do

A payment is **two direct transfers in one transaction**: payer → merchant for
the full amount, payer → `feeCollector` for a flat fee. The contract never
holds a balance and has no withdrawal, sweep, or rescue path for user funds.
The owner can configure per-token fees, change the fee collector, and
`pause()`/`unpause()` — it **cannot** move, retain, or redirect merchant money.

| Function | Purpose |
|---|---|
| `quoteFee(token, amount)` | view — the exact fee the chain will charge (what the checkout displays) |
| `pay(invoiceId, merchant, token, amount, maxFee)` | ERC-20 payment; reverts if the quoted fee exceeds the payer's `maxFee` (no fee-config front-running) |
| `payWithPermit(...)` | same, attempting an EIP-2612 permit first — `try/catch` fallback covers non-conforming tokens (USDT, DAI) |
| `payNative(invoiceId, merchant, amount, maxFee)` | native ETH payment with `msg.value` validation |

Emits `PaymentMade(invoiceId, merchant, payer, token, amount, fee,
blockTimestamp)` — the event the backend indexer settles payment intents
against. Config events: `FeeConfigSet`, `FeeCollectorSet`.

## Fee model

Flat and EUR-denominated per token — never a percentage, no price oracle:
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
| `src/RSendsRouter.sol` | the router (only production contract) |
| `test/RSendsRouter.t.sol` | 34 tests: fee math, maxFee guard, permit fallback, pause, ownership; mocks incl. `MockERC20Permit`, USDT-style no-return, fee-on-transfer |
| `test/SetFeeConfig.t.sol` | registry ↔ on-chain config integration |
| `script/SetFeeConfig.s.sol` | wires per-chain token policy from the registry; asserts on-chain `symbol()`/`decimals()` before whitelisting; signs via Foundry keystore (`--account`), never a raw key |
| `script/E2EDeploy.s.sol` | local-Anvil fixture (mock tokens) for the repo-root `make e2e-anvil` money-path E2E |
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

## Deploy (Base Sepolia — testnet)

There is intentionally **no testnet deploy script**; deploy directly with
`forge create` using a Foundry keystore (`cast wallet import` — the private key
never appears in env, files, or shell history). Constructor:
`RSendsRouter(address initialOwner, address initialFeeCollector)`. Then run
`SetFeeConfig.s.sol` **as the owner** to whitelist tokens from the registry.

The full step-by-step (keystore setup, verification, wiring the address into
backend and frontend env) lives in the repo-root
[`DEPLOY_RUNBOOK.md`](../../DEPLOY_RUNBOOK.md), Part 1.

## Dependencies

- OpenZeppelin Contracts v5 (`SafeERC20`, `IERC20Permit`, `ReentrancyGuard`,
  `Pausable`, `Ownable2Step`)
- Foundry (forge, cast, anvil)
