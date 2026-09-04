# Spike: RSendsAutoSplit on TRON

Throwaway. Not production. Nile testnet only.

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
