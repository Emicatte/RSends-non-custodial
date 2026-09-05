# Spike: RSendsAutoSplit on TRON

Throwaway. Not production. Nile testnet only.

Settled two inferences from the TRON research pass:
1. does tronprotocol solc 0.8.31 compile RSendsAutoSplit against OZ 5.6.1?  -> STEP 1
2. does a 10-leg TRC-20 split fit inside getMaxCpuTimeOfOneTx?             -> STEP 2

`src/RSendsAutoSplit.sol` is a COPY of the Base source taken from the branch
that owns it. Exactly one line differs -- the pragma. The Base source, its
artifact and its deploy script are not touched by this spike.

    node compile.js <soljson> <oz-contracts-dir> <src> [evmVersion]

Compiler: https://tronprotocol.github.io/solc-bin/wasm/soljson-v0.8.31+commit.c2812a3d.js
sha256 d0f2092759c99c3e983cf3dce38f75eb32377bf4cfc904cf34c2a6f8b04356b8 (verified,
re-verified on the 2026-09-05 redeploy). TronBox cannot drive 0.8.31 -- maxVersion
is 0.8.25 in the installed 4.6.0 and 0.8.29 in the latest 4.10.0 -- so the wasm
soljson is driven directly through solc/wrapper, which is what TronBox does
internally minus its version gate.

## Current deployment (Nile)

`deployed.json` -> **TYi2uuk9SKA9tyP4iRQJs5sNHU3wdHURAo**, runtime 4343 bytes,
keccak `0x5c656773c7bdb1c947769e38fe629321a4ec90383f2798650ca2daeea312daab`,
verified byte-for-byte against `wallet/getcontractinfo`.

Source: the corrected contract carrying the `SelfRecipient` check
(`fix/autosplit-exclude-merchant`). Measurements in `measurements.jsonl`.

## Retired deployments

`retired.json` is the durable record; `deploy.js` appends to it automatically
before overwriting `deployed.json`, so an address cannot silently stay
"current" after being superseded.

**TWd6ezLhi7NMYv2bgRp9xyxEWiRfzCj3xh -- RETIRED 2026-09-05.** It predates the
SelfRecipient fix, so `setPolicy` there still accepts the merchant as its own
recipient and the zero-balance invariant can be broken. Its measurements are in
`measurements.retired-TWd6ez.jsonl` (same three labels as the current file --
they are NOT interchangeable; check the block numbers or the `contract` field).
Its allowance from the spike merchant is also still bricked at 12345 from the
guard probe and was never reset. Do not reuse this address for anything.

## Measurement note that is easy to get wrong

`run.js` derives recipients from a seed, and "cold" means those addresses have
never held USDT. After a run they hold it, so REUSING A SEED silently measures
the warm path. The 2026-09-05 redeploy used fresh seeds (`coldA2`/`coldB2`)
precisely because `coldA`/`coldB` had been warmed by the original spike --
reusing them would have shown a ~150k energy "improvement" that is only the
SSTORE zero->nonzero premium going missing.
