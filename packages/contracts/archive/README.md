# archive/ — quarantined contracts (NOT compiled, NOT product)

These contracts were moved out of `src/`, `test/`, `script/` so `forge` stops
compiling them. They are **not** part of the non-custodial RSendsRouter payment
product. Nothing here is built or deployed by the current toolchain (foundry only
compiles `src/`, `test/`, `script/` + `lib/`); the `src/test/script` substructure is
preserved here so relative imports still resolve if you ever compile a subset.

Quarantined rather than deleted (reversible) per the verify-then-remove policy.

## Clearly legacy — superseded by RSendsRouter (safe to delete later)
- `src/FeeRouter.sol`, `FeeRouterV3/V4/V4_1/V5/V6.sol` — the old oracle/%-split fee
  router lineage. RSendsRouter (flat-fee, non-custodial) replaces all of these.
- `src/Counter.sol` — Foundry scaffolding example.
- `script/Deploy.s.sol` (FeeRouterV3), `DeployV4.s.sol`, `DeployAllChains.s.sol`,
  `DeployMultiChain.s.sol`, `RedeployBaseSwapFix.s.sol`, `SetupTokens.s.sol`
  (FeeRouterV4 allowlist), `Counter.s.sol`, `StressMaxRecipients.s.sol` — legacy
  deploy/util scripts for the above.
- `test/FeeRouterV4.t.sol`, `FeeRouterV4_1.t.sol`, `FeeRouterV5.t.sol`,
  `FeeRouterV6.t.sol`, `Counter.t.sol`.

## ⚠️ FLAGGED — needs a product-owner decision (do NOT delete yet)
The **RSend\*** family is RSend-branded and has tests, but is NOT part of the
non-custodial RSendsRouter payment path. Confirm whether these are a separate
shipping product (then move back / give their own package) or truly dead:
- `src/RSendBatchDistributor.sol` (+ `test/RSendBatchDistributor.t.sol`)
- `src/RSendCCIPReceiver.sol`, `RSendCCIPReceiverV2.sol` (+ `test/RSendCCIPReceiverV2.t.sol`),
  `src/RSendCCIPSender.sol`, `RSendCCIPSenderV2.sol` (+ `test/RSendCCIPSenderV2.t.sol`),
  and `script/DeployCCIP.s.sol` (note: it references the V1 CCIP contracts while V2 exist).
- `src/RSendForwarder.sol`, `RSendForwarderV2.sol` (+ `test/RSendForwarderV2.t.sol`).

## Product (still compiled, NOT here)
`src/RSendsRouter.sol`, `test/RSendsRouter.t.sol`, `test/SetFeeConfig.t.sol`,
`test/mocks/E2EMocks.sol`, `script/SetFeeConfig.s.sol`, `script/E2EDeploy.s.sol`.
