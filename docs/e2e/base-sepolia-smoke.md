# Base Sepolia money-path smoke (MANUAL — not in CI)

A one-shot, by-hand smoke of the real money-path against **Base Sepolia** for the
final pre-mainnet check. This is intentionally **NOT automated and NOT wired into
CI** — the deterministic coverage lives in the local Anvil E2E (`make e2e-anvil`).
Run this manually before a mainnet deploy.

> The automated, deterministic loop is the Anvil E2E:
> [`services/backend/tests/e2e/test_money_path_anvil.py`](../../services/backend/tests/e2e/test_money_path_anvil.py),
> run with `make e2e-anvil`. This doc is the manual testnet counterpart.

## Secrets policy (read first)

- **Use a throwaway burner key with testnet funds only.** Never a key that holds
  real value. Never hardcode or commit a key.
- **Everything sensitive comes from ENV only** (`BURNER_PRIVATE_KEY`,
  `SEPOLIA_RPC_URL`). Nothing is written to disk or printed.
- Get Base Sepolia ETH from a faucet and test USDC
  (`0x036CbD53842c5426634e7929541eC2318f3dCF7e`, 6 dec) from Circle's faucet.

## Prerequisites

- Foundry (`forge`, `cast`) and Python E2E deps (`pip install -r services/backend/requirements-e2e.txt`).
- A deployed `RSendsRouter` on Base Sepolia with `setFeeConfig` for the token(s)
  you test, `enabled=true`. Deploy with [`packages/contracts/script/SetFeeConfig.s.sol`](../../packages/contracts/script/SetFeeConfig.s.sol)
  (or your existing testnet deployment). Record `ROUTER_ADDRESS`.
- The burner address funded with: Base Sepolia ETH (gas) + test USDC ≥ amount+fee.

## Required ENV

```bash
export SEPOLIA_RPC_URL="https://sepolia.base.org"   # or your provider URL
export BURNER_PRIVATE_KEY="0x..."                    # throwaway, testnet only
export ROUTER_ADDRESS="0x..."                        # deployed RSendsRouter on 84532
export USDC_ADDRESS="0x036CbD53842c5426634e7929541eC2318f3dCF7e"
# Optional: a non-permit ERC20 you control to also smoke the approve+pay branch
export USDT_ADDRESS="0x..."                          # optional
```

## Checklist

1. **Sanity** — confirm chain + balances:
   ```bash
   cast chain-id --rpc-url "$SEPOLIA_RPC_URL"          # 84532
   cast call "$USDC_ADDRESS" "balanceOf(address)(uint256)" <burner> --rpc-url "$SEPOLIA_RPC_URL"
   ```
2. **Fee config present** — `cast call "$ROUTER_ADDRESS" "quoteFee(address,uint256)(uint256)" "$USDC_ADDRESS" 1000000 --rpc-url "$SEPOLIA_RPC_URL"` returns the flat fee (e.g. `150000`).
3. **USDC via payWithPermit** — run the optional script (below) or do it by hand:
   sign an EIP-2612 permit for `value = amount + maxFee`, then call
   `payWithPermit(invoiceId, merchant, USDC, amount, maxFee, deadline, v, r, s)`.
4. **USDT via approve+pay** (if `USDT_ADDRESS` set) — `approve(router, amount+maxFee)`
   then `pay(invoiceId, merchant, USDT, amount, maxFee)`.
5. **Confirm on-chain** — both txs succeed and emit `PaymentMade`; the merchant got
   `amount` and the feeCollector got `fee`.
6. **Backend + webhook** — point a temporary backend at Base Sepolia and confirm
   the invoice flips to **paid** and a **signed** `payment.completed` webhook is
   delivered and verifies:
   ```bash
   cd services/backend
   export DATABASE_URL="sqlite+aiosqlite:///./sepolia_smoke.db"
   export INDEXER_USE_FINALIZED_TAG=false
   export INDEXER_CONFIRMATIONS=2
   export RSENDS_ROUTER_ADDRESSES_JSON="{\"84532\": \"$ROUTER_ADDRESS\"}"
   # Register a merchant webhook pointing at a receiver you control, create an
   # intent on chain "base_sepolia", pay it (step 3/4), then let the indexer run.
   ```
   Verify the delivered webhook with
   [`verify_webhook_signature`](../../services/backend/app/services/webhook_service.py)
   and the merchant's secret (headers `X-RSend-Signature` / `X-RSend-Timestamp`).

## Optional one-shot script

[`services/backend/scripts/sepolia_smoke.py`](../../services/backend/scripts/sepolia_smoke.py)
performs the on-chain half (steps 3–5) from ENV: it refuses to run unless the
required ENV is set, never prints the key, signs the permit, submits
`payWithPermit` (and `approve`+`pay` if `USDT_ADDRESS` is set), and confirms the
`PaymentMade` events + merchant/feeCollector balance deltas.

```bash
cd services/backend
python scripts/sepolia_smoke.py
```

The backend/webhook half (step 6) stays manual — run a temporary backend as above
and confirm the signed webhook by hand. **Do not add any of this to CI.**
