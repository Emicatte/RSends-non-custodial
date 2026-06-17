# Stress Test S2 — 20 Sequential Batches (Nonce Management)

**Date:** 2026-04-04
**Network:** Base Sepolia (chain ID 84532)
**Contract:** `0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3`
**Deployer:** `0xa61A471FC226a06C681cf2Ec41d2C64a147b4392`
**ETH/batch:** 0.0015 ETH *(original target: 0.005 ETH — reduced due to testnet budget)*

---

## Send Phase Results

| Batch | Nonce | Send Status | Gas Used | Block | Send Time | Confirm |
|-------|-------|-------------|----------|-------|-----------|--------|
| 1 | 51 | SENT | 413481 | 39768863 | 210ms | SUCCESS |
| 2 | 52 | SENT | 413493 | 39768863 | 208ms | SUCCESS |
| 3 | 53 | SENT | 413493 | 39768863 | 236ms | SUCCESS |
| 4 | 54 | SENT | 413481 | 39768864 | 811ms | SUCCESS |
| 5 | 55 | SENT | 413481 | 39768864 | 253ms | SUCCESS |
| 6 | 56 | SENT | 413493 | 39768864 | 242ms | SUCCESS |
| 7 | 57 | SENT | 413469 | 39768864 | 256ms | SUCCESS |
| 8 | 58 | SENT | 413481 | 39768864 | 252ms | SUCCESS |
| 9 | 59 | SENT | 413481 | 39768864 | 204ms | SUCCESS |
| 10 | 60 | SENT | 413481 | 39768864 | 270ms | SUCCESS |
| 11 | 61 | SENT | 413493 | 39768865 | 244ms | SUCCESS |
| 12 | 62 | SENT | 413481 | 39768865 | 279ms | SUCCESS |
| 13 | 63 | SENT | 413493 | 39768865 | 234ms | SUCCESS |
| 14 | 64 | SENT | 413493 | 39768865 | 242ms | SUCCESS |
| 15 | 65 | SENT | 413493 | 39768865 | 234ms | SUCCESS |
| 16 | 66 | SENT | 413469 | 39768865 | 255ms | SUCCESS |
| 17 | 67 | SENT | 413493 | 39768865 | 228ms | SUCCESS |
| 18 | 68 | SENT | 413493 | 39768865 | 218ms | SUCCESS |
| 19 | 69 | SENT | 413469 | 39768866 | 229ms | SUCCESS |
| 20 | 70 | SENT | 413481 | 39768866 | 252ms | SUCCESS |

---

## Summary

| Metric | Value |
|--------|-------|
| Batches sent | 20 |
| Confirmed | 20/20 |
| Reverted | 0 |
| Failed/Timeout | 0 |
| Total send time | 5.37s |
| Avg send latency | 268.5ms/batch |
| Send throughput | 3.7 batches/s |
| Confirm wait | 2.2s |
| Nonce gaps | None |
| Balance before | 0.033896 ETH |
| Balance after | 0.003997 ETH |
| Total spent | 0.029900 ETH |
| Recipients served | 200 |

---

## Balance Verification (5 random recipients)

| Batch | Index | Address | Balance (wei) | Match |
|-------|-------|---------|---------------|-------|
| 4 | — | `0xa7340906d7bD6e35d86cc24440b68278638eEdcE` | 149250000000000 | ✓ OK |
| 20 | — | `0x04178D183e72ca0222a09ddAFa1cf0906F65Afe4` | 149250000000000 | ✓ OK |
| 11 | — | `0xC3e5a26093d2bF5845b7908148AEE14f92FB81d1` | 149250000000000 | ✓ OK |
| 18 | — | `0x24EDd40505f40F4cc2f9c5aD1b96130c2a6b7202` | 149250000000000 | ✓ OK |
| 1 | — | `0x302173a93FA1F52D509811B8A2E7a7F70B8e3892` | 149250000000000 | ✓ OK |

---

## Volume Scaling Analysis

*(ETH price assumed: $2,300)*

| Scenario | ETH/batch | Total ETH (20 batches) | USD Value |
|----------|-----------|------------------------|----------|
| **This test** | 0.0015 ETH | 0.03 ETH | $69 |
| Target (original) | 0.005 ETH | 0.10 ETH | $230 |
| Prod (5 ETH/batch) | 5 ETH | 100 ETH | $230,000 |
| Scale to $1M | ~21.7 ETH/batch | ~435 ETH | $1,000,000 |

**Throughput extrapolation:** at 3.7 batches/s, this system can process **13409 batches/hour**.

At prod scale (5 ETH/batch): **$154,206,975/hour** capacity.
