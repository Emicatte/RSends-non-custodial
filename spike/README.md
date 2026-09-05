# Spike: RSendsAutoSplit on TRON

Throwaway. Not production. Nile testnet only.

> **RETIRED 2026-09-05 — do not deploy from, or measure against, this record.**
> The address this spike deployed, `TWd6ezLhi7NMYv2bgRp9xyxEWiRfzCj3xh`, predates
> the SelfRecipient fix: `setPolicy` there still accepts the merchant as its own
> recipient, so the zero-balance invariant this spike measured can be broken and
> the residue re-split by any caller. The spike merchant's allowance to it is also
> still bricked at 12345 from the guard probe.
>
> Superseded by **`TYi2uuk9SKA9tyP4iRQJs5sNHU3wdHURAo`** (runtime 4343 bytes,
> keccak `0x5c656773c7bdb1c947769e38fe629321a4ec90383f2798650ca2daeea312daab`),
> deployed on branch `spike/tron-autosplit-redeploy`, which carries the corrected
> contract and the re-run measurements. The energy figures recorded HERE remain
> valid — they reproduced exactly on the new deployment — but they were taken
> against the uncorrected contract, and `deployed.json` on this branch points at
> the retired address.

Settles two inferences from the TRON research pass:
1. does tronprotocol solc 0.8.31 compile RSendsAutoSplit against OZ 5.6.1?  -> STEP 1
2. does a 10-leg TRC-20 split fit inside getMaxCpuTimeOfOneTx?             -> STEP 2

`src/RSendsAutoSplit.sol` is a COPY of the Base source taken from
feat/auto-split-contract. Exactly one line differs -- the pragma. The Base
source and its artifact are not touched by this spike.

    node compile.js <soljson> <oz-contracts-dir> <src> [evmVersion]

Compiler: https://tronprotocol.github.io/solc-bin/wasm/soljson-v0.8.31+commit.c2812a3d.js
sha256 d0f2092759c99c3e983cf3dce38f75eb32377bf4cfc904cf34c2a6f8b04356b8 (verified).
TronBox cannot drive 0.8.31 -- maxVersion is 0.8.25 in the installed 4.6.0 and
0.8.29 in the latest 4.10.0 -- so the wasm soljson is driven directly through
solc/wrapper, which is what TronBox does internally minus its version gate.
