# RSendsRouterV2 — audit handoff (RPagos)

This note states the design decisions of the fee-less mainnet router **with
their consequences**, up front. Each of these is a deliberate choice with the
reasoning recorded here — none is an omission.

## What the contract is

[`src/RSendsRouterV2.sol`](src/RSendsRouterV2.sol): single-merchant payment
router, **payer → merchant only**. One `safeTransferFrom` (or one native
`call{value}`) per payment, for exactly `amount`. No fee transfer, no fee
state, no fee events. Monetization is a flat off-chain subscription — nothing
about pricing exists on-chain.

Deployed ALONGSIDE the immutable testnet `RSendsRouter` (v1, which keeps its
on-chain flat fee on Base Sepolia) and `RSendsSplitRouter` (the shipped
ownerless/fee-less N-way splitter this contract's model follows).

## Decision 1 — fully ownerless

`RSendsRouterV2 is ReentrancyGuard` and nothing else. No `Ownable`, no
`Pausable`, no configuration functions, no privileged role of any kind.

**Why.** The v1 owner existed for three capabilities: fee configuration
(`setFeeConfig`/`setFeeCollector`), the pause kill-switch, and the token
whitelist (fused into `feeConfig.enabled`). Removing the fee removes the
first outright. The remaining two were evaluated and deliberately dropped:

- **Pause** protects no funds: the contract never holds a balance (no
  `receive`/`fallback`, exact `msg.value` match, no rescue/sweep, no proxy),
  so a pause could only stop new payments *through this contract* — payers
  can always transfer directly. A pause is a rail kill-switch and therefore a
  denial-of-service lever held by a key; with no funds at risk it defends
  nothing and creates an admin surface to attack.
- **The token whitelist** duplicated an off-chain control (see Decision 2).

An ownerless contract has no key to protect, no admin surface to defend, and
no control point that could ever redirect, freeze, or custody a payment. This
is the strongest form of the software-vendor position: RSends *cannot*
intervene in the money path, by construction.

**Pinned by tests**: `test/RSendsRouterV2.t.sol::
test_noOwnerSurface_v1SelectorsAllRevert` calls every v1 owner/fee selector
verbatim (`owner`, `pause`, `setFeeConfig`, `setFeeCollector`, `quoteFee`,
`feeCollector`, `transferOwnership`, …) and asserts each reverts;
`test_plainEthSend_reverts_noReceive` and
`test_forcedBalance_isUnreachable_paymentsUnaffected` pin the no-custody
side.

## Decision 2 — no on-chain token whitelist: token verification is one line of defense, and it lives off-chain

This is the consequence of Decision 1 that must be understood, not
discovered: **token checking went from two lines of defense to one.**

On v1, a payment through a token the owner had not enabled reverted on-chain
(`feeConfig[token].enabled`). On v2 the contract accepts any ERC-20 address
(only a zero-address shape guard exists — `ZeroToken` is not a whitelist).
The surviving token verification is entirely off-chain, in two places:

1. **Intent creation (load-bearing).** An intent can only be born on a token
   the backend registry has `enabled` (`token_is_enabled`, called in
   `intent_service.create_intent` — the single construction site). This is
   now the ONLY thing preventing a payment intent on an arbitrary or
   fee-on-transfer token, and it is explicitly load-bearing: weakening it is
   a security regression even though no contract changes. The damage scenario
   it defends against is not a griefer (the settlement match eats that) but a
   merchant-created intent on a FoT/unregistered token, where the payer would
   part with funds that arrive short and settle nothing. **Pinned by
   `services/backend/tests/test_creation_token_gate.py`**: registry-absent
   and registry-disabled tokens are rejected 400 `UNSUPPORTED_TOKEN` with no
   intent row born, plus a control proving the rejection is attributable to
   this gate (with the gate mocked open the identical request succeeds) —
   the Pydantic schema whitelist alone is NOT sufficient (it admits
   registry-absent/disabled symbols).
2. **Settlement matching.** The indexer's event↔intent match
   (`_validate_event_against_intent`,
   `services/backend/app/services/payment_indexer.py`) rejects a settlement
   event whose token differs from the intent's — the settlement is recorded
   `rejected` and the intent is **never mutated** (a stranger's payment in a
   wrong token cannot flip an invoice to paid).

Why this is coherent with the model: the whitelist never protected funds —
the router holds none — it only mirrored, on-chain, a decision the backend
already makes at intent creation. What is genuinely lost is an on-chain
revert for a payer who hand-crafts a call with a weird token outside any
intent; that payment settles merchant-side like any direct wallet-to-wallet
transfer would (which was always possible without the router) and will never
match an intent.

**Fee-on-transfer tokens** are the concrete case: the contract does not (and
cannot, without a whitelist) guarantee the merchant receives `amount` on a
FoT token. `test_pay_feeOnTransfer_merchantReceivesLess` documents the
behavior in-contract; the registry gate at creation is what keeps such tokens
out of real intents.

## Decision 3 — new 6-arg event (no fee word), dual-topic indexer

`PaymentMade(bytes32 invoiceId, address merchant, address payer, address
token, uint256 amount, uint256 blockTimestamp)` — same indexed topology as
v1 minus the `fee` word. An always-zero fee field would have advertised fee
machinery in the ABI forever; the schema now claims nothing that isn't true.

Both shapes, keyed by `topics[0]`:

| Router | Signature | topic0 |
|---|---|---|
| v2 (fee-less) | `PaymentMade(bytes32,address,address,address,uint256,uint256)` | `0xc3e210e146bbcd43de924ac66fa9d284db14f167144f83b2bcf40a40cc843241` |
| v1 (testnet) | `PaymentMade(bytes32,address,address,address,uint256,uint256,uint256)` | `0xab7ccb7fe7da5e22a3f0005fe67aa4652cd87b623e108b54088210d0deb04947` |

The backend watcher filters on **both** topics and dispatches by
`(address, topic0)` pairing (a v2-shaped log claiming the v1 address is
dropped). The hashes are pinned as **literals** on both sides —
`test/RSendsRouterV2.t.sol::test_eventTopic_pinnedLiteral` (Solidity) and
`services/backend/tests/test_indexer_topic_hashes.py` (Python) — because a
missed topic is the silent failure mode: payments invisible while the system
reports itself healthy. An end-to-end Anvil test
(`services/backend/tests/e2e/test_money_path_anvil_v2.py`) proves the whole
loop: single transfer, **zero** fee-collector delta, zero router balance,
settlement recorded with fee 0, signed webhook.

## Deployment surface

- Constructor takes **no arguments** — there is nothing to configure, ever.
  [`script/DeployRouterV2.s.sol`](script/DeployRouterV2.s.sol).
- `script/SetFeeConfig.s.sol` is v1-only and must never be pointed at a v2
  deployment (v2 has no fee config and no owner to call it — any such call
  reverts; the registry `_comment` documents the same).
- Backend cutover is one env var: `RSENDS_ROUTER_V2_ADDRESSES_JSON`
  (chain → address). A chain in that map creates v2 intents; the indexer
  watches v1 and v2 side by side, so in-flight v1 payments still settle.
- No proxy, no upgrade path: changing the contract means deploying a new
  address and moving the env var. Immutability is the feature.
