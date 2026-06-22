# RSends Non-Custodial — Deploy Runbook (Base Sepolia / testnet)

This runbook deploys the **non-custodial** stack: an `RSendsRouter` contract on
Base Sepolia (chainId **84532**), a FastAPI backend + Celery + the on-chain
`PaymentMade` indexer on **Render**, and the Next.js frontend on **Vercel**.

> **Architecture this reflects (verified against the code, not assumed):**
> - The **indexer runs inside the FastAPI app lifespan** (`app/main.py →
>   start_indexer_if_needed`), not as a Celery beat task. ⇒ the web service is
>   **single-instance** (`numInstances: 1`); scaling it = N duplicate indexers.
> - **Celery** has a **worker** (queues `notify`/`confirm`/`analytics`/`default`)
>   and a **beat** (`process_webhook_deliveries` 15s, `expire_pending_intents`
>   60s, daily GDPR deletion). Beat is **single-instance** (else double-fires).
> - Health is **`/health`** (probes Redis). `/health/sweep` no longer exists.
> - DB access is **asyncpg only** (no psycopg2) ⇒ `DATABASE_URL` must use the
>   `postgresql+asyncpg://` scheme.
> - There is **no testnet contract deploy script** — `script/E2EDeploy.s.sol`
>   deploys **mock** tokens for local Anvil. Real testnet deploy uses
>   `forge create` (below).

Legend: **[AUTO]** = done by Render/Vercel/CI · **[AZIONE UTENTE]** = you do it
(account, key, DNS, dashboard).

---

## ⚠️ Read first

1. **Fresh database.** The Render Postgres starts empty so `alembic upgrade head`
   runs clean `0001 → 0004`. The old dev DB carried a **stale Classic stamp
   (0038)** — **never** point this deploy at it.
2. **Testnet guard posture.** `config.py` sets `is_prod = (not DEBUG) or
   ENVIRONMENT startswith "prod"`. To relax prod-only guards on testnet you need
   **both `ENVIRONMENT=development` and `DEBUG=true`** (set in `render.yaml`).
   `ENVIRONMENT=development` alone does **not** relax them. `ALCHEMY_API_KEY` is
   **always** required regardless.
3. **Keys never touch the repo.** The deployer private key lives in a Foundry
   keystore (`cast wallet import`) or a gitignored shell env var — never in a
   committed file, command, or log.

---

## Order of operations

```
[1] Contract  → deploy RSendsRouter + SetFeeConfig on Base Sepolia   (gives router addr)
[2] Backend   → Render Blueprint (DB, Redis, web+indexer, worker, beat)
[3] Frontend  → Vercel (root = apps/web)
[4] Wire-up   → paste router addr + matching secrets across all three
[5] Smoke test
```

---

## Part 1 — Contract on Base Sepolia (RUNBOOK — do not run from CI)

### Prerequisites **[AZIONE UTENTE]**
- **Foundry** installed (`foundryup`).
- **Deployer wallet** funded with Base Sepolia ETH — faucet:
  https://www.alchemy.com/faucets/base-sepolia (or Coinbase CDP faucet).
- **RPC URL** for Base Sepolia (public `https://sepolia.base.org`, or an Alchemy
  `https://base-sepolia.g.alchemy.com/v2/<KEY>`).
- **(optional) BaseScan API key** for verification: https://basescan.org/myapikey
- Decide two addresses:
  - `OWNER` — owns the router (the only address allowed to run `SetFeeConfig`).
  - `FEE_COLLECTOR` — receives fees.

### 1a. Import the deployer key into Foundry's keystore **[AZIONE UTENTE]**
```bash
cast wallet import rsends-deployer --interactive   # paste the private key ONCE; prompts for a password
# → referenced below as --account rsends-deployer ; the raw key never appears again
```

### 1b. Deploy `RSendsRouter` **[AZIONE UTENTE]**
There is no testnet deploy *script*; deploy the contract directly. Constructor is
`RSendsRouter(address initialOwner, address initialFeeCollector)`.
```bash
cd packages/contracts
export BASE_SEPOLIA_RPC="https://sepolia.base.org"        # or your Alchemy URL

forge create src/RSendsRouter.sol:RSendsRouter \
  --rpc-url "$BASE_SEPOLIA_RPC" \
  --account rsends-deployer \
  --constructor-args <OWNER_ADDRESS> <FEE_COLLECTOR_ADDRESS> \
  --broadcast \
  --verify --verifier etherscan --etherscan-api-key <BASESCAN_API_KEY>   # drop --verify if no key
```
Capture **`Deployed to: 0x…`** from the output → this is **`<ROUTER_ADDRESS>`**.

### 1c. Wire the token fee config from the registry **[AZIONE UTENTE]**
`SetFeeConfig.s.sol` reads `services/backend/app/token_registry.json` for the
current chainId (84532 → `ETH` skipped as native, `USDC` enabled+verified). It
asserts the on-chain `symbol()`/`decimals()` of the registry USDC address
(`0x036CbD53842c5426634e7929541eC2318f3dCF7e`) before whitelisting — a wrong
address reverts. **The signer here must be the router `OWNER`** (`setFeeConfig`
is `onlyOwner`).

This script reads the key from the **`PRIVATE_KEY` env var** (its design —
`vm.envUint("PRIVATE_KEY")`), so for this step export it in your shell only:
```bash
cd packages/contracts
export PRIVATE_KEY=<OWNER_private_key>      # shell only; never committed/logged
export ROUTER_ADDRESS=<ROUTER_ADDRESS>

forge script script/SetFeeConfig.s.sol:SetFeeConfig \
  --rpc-url "$BASE_SEPOLIA_RPC" \
  --broadcast
unset PRIVATE_KEY
```

### 1d. Record the router address **[AZIONE UTENTE]**
You'll paste `<ROUTER_ADDRESS>` into:
- backend `RSENDS_ROUTER_ADDRESSES_JSON={"84532":"<ROUTER_ADDRESS>"}`
- frontend `NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA=<ROUTER_ADDRESS>`

---

## Part 2 — Backend on Render (Blueprint)

### 2a. Create the Blueprint **[AZIONE UTENTE → AUTO]**
1. Push this repo to your private GitHub remote (see the separate push handover).
2. Render → **New → Blueprint** → pick the repo. Render reads [`render.yaml`](render.yaml)
   and provisions: `rsends-db` (Postgres), `rsends-redis`, `rsends-api` (web +
   indexer), `rsends-worker`, `rsends-beat`. **[AUTO]**

### 2b. Fill the `sync: false` env vars **[AZIONE UTENTE]**
In the `rsends-shared` env group (Render dashboard):

| Var | Value |
|---|---|
| `DATABASE_URL` | Render `rsends-db` **Internal** URL, **scheme rewritten** to `postgresql+asyncpg://…` |
| `REDIS_URL` | `rsends-redis` Internal URL + `/0` |
| `CELERY_BROKER_URL` | same Redis URL + `/1` |
| `CELERY_RESULT_BACKEND` | same Redis URL + `/2` |
| `ALCHEMY_API_KEY` | your Alchemy key (always required) |
| `INDEXER_RPC_URLS_JSON` | `{"84532":"https://base-sepolia.g.alchemy.com/v2/<KEY>"}` |
| `RSENDS_ROUTER_ADDRESSES_JSON` | `{"84532":"<ROUTER_ADDRESS>"}` (from Part 1) |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://<app>.vercel.app` |
| `APP_URL` | same Vercel URL |
| `GOOGLE_OAUTH_CLIENT_ID`, `RESEND_API_KEY` | optional on testnet |

`HMAC_SECRET`, `INTERNAL_PROXY_SECRET`, `AUTH_JWT_SECRET` are **[AUTO]**
generated by Render — note `HMAC_SECRET` and `INTERNAL_PROXY_SECRET` (you copy
them to Vercel in Part 4).

### 2c. Deploy **[AUTO]**
Render runs `preDeployCommand: alembic upgrade head` (clean `0001→0004`), then
starts the three services. Confirm `https://rsends-api.onrender.com/health`
returns `{"status":"healthy"}`.

---

## Part 3 — Frontend on Vercel

### 3a. Project settings **[AZIONE UTENTE]** (no `vercel.json` needed)
This is a monorepo; point Vercel at the app and let it auto-detect Next.js:

| Setting | Value |
|---|---|
| **Root Directory** | `apps/web` |
| Framework Preset | Next.js (auto) |
| Build Command | `next build` (auto) |
| Install Command | `npm install` (auto) |
| Node version | 20.x |

> A `vercel.json` is intentionally **not** committed: with Root Directory =
> `apps/web`, Vercel's Next.js preset handles build/output correctly. Adding a
> redundant `vercel.json` would only risk drift.

### 3b. Env vars **[AZIONE UTENTE]**
Set from [`apps/web/.env.production.example`](apps/web/.env.production.example).
Required minimum: `NEXT_PUBLIC_WC_PROJECT_ID`, `RPAGOS_BACKEND_URL` (+ the two
`NEXT_PUBLIC_` URL twins), `INTERNAL_PROXY_SECRET`, `HMAC_SECRET`,
`NEXT_PUBLIC_TARGET_CHAIN_ID=84532`, `ALLOWED_ORIGINS`,
`NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA`.

---

## Part 4 — Wire-up (the matching values) **[AZIONE UTENTE]**

These MUST match across services or auth/webhooks break:

| Value | Backend (Render) | Frontend (Vercel) |
|---|---|---|
| Internal proxy secret | `INTERNAL_PROXY_SECRET` | `INTERNAL_PROXY_SECRET` (same) |
| HMAC secret | `HMAC_SECRET` | `HMAC_SECRET` (same) |
| Router address | `RSENDS_ROUTER_ADDRESSES_JSON` `{"84532":"…"}` | `NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA` (same addr) |
| Public URLs | `CORS_ORIGINS`/`APP_URL` = Vercel URL | `RPAGOS_BACKEND_URL` = Render URL |

After editing env on either side, **redeploy** that service.

---

## Part 5 — Smoke test **[AZIONE UTENTE]**
1. `GET https://rsends-api.onrender.com/health` → `healthy`.
2. Render `rsends-api` logs show the indexer started for chain `84532`.
3. Open the Vercel app → create a payment intent → the `/pay/[intentId]` page
   loads and reads the router address from the intent.
4. Pay with a Base Sepolia testnet wallet (USDC `0x036CbD…` or native ETH);
   confirm the indexer picks up `PaymentMade` and the intent settles.
5. Confirm a merchant webhook is delivered (the beat 15s loop → worker).

---

## Master ENV checklist

**SECRET** = dashboard only, never in the repo. **PUBLIC** = safe to expose.

### Backend (Render `rsends-shared`)
| Name | What | Class | Where to get it | Placeholder |
|---|---|---|---|---|
| `DATABASE_URL` | Postgres DSN (asyncpg) | SECRET | Render DB Internal URL, scheme `+asyncpg` | `postgresql+asyncpg://u:p@host:5432/rsends` |
| `REDIS_URL` | cache/idempotency | SECRET | Render Redis Internal URL `/0` | `redis://host:6379/0` |
| `CELERY_BROKER_URL` | Celery broker | SECRET | Redis URL `/1` | `redis://host:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery results | SECRET | Redis URL `/2` | `redis://host:6379/2` |
| `HMAC_SECRET` | inbound callback HMAC (≥32) | SECRET | Render generateValue | (auto) |
| `INTERNAL_PROXY_SECRET` | gates `/api/internal/*` | SECRET | Render generateValue | (auto) |
| `AUTH_JWT_SECRET` | session JWT (≥64 prod) | SECRET | Render generateValue | (auto) |
| `ALCHEMY_API_KEY` | RPC (always required) | SECRET | dashboard.alchemy.com | `<alchemy_key>` |
| `RSENDS_ROUTER_ADDRESSES_JSON` | chain→router map | PUBLIC | Part 1 deploy output | `{"84532":"<FILL_AFTER_CONTRACT_DEPLOY>"}` |
| `INDEXER_RPC_URLS_JSON` | chain→RPC map | SECRET (has key) | Alchemy | `{"84532":"https://base-sepolia.g.alchemy.com/v2/<KEY>"}` |
| `CORS_ORIGINS` | allowed origins | PUBLIC | your Vercel URL | `https://<app>.vercel.app` |
| `ENVIRONMENT` / `DEBUG` | guard posture | PUBLIC | testnet: `development` / `true` | — |
| `GOOGLE_OAUTH_CLIENT_ID` | Google login | SECRET | Google Cloud Console | (optional testnet) |
| `RESEND_API_KEY` | email | SECRET | resend.com | (optional testnet) |

### Frontend (Vercel)
| Name | What | Class | Where to get it | Placeholder |
|---|---|---|---|---|
| `NEXT_PUBLIC_WC_PROJECT_ID` | WalletConnect | PUBLIC | cloud.walletconnect.com | `<wc_project_id>` |
| `RPAGOS_BACKEND_URL` | backend (server) | PUBLIC | Render web URL | `https://rsends-api.onrender.com` |
| `NEXT_PUBLIC_RPAGOS_BACKEND_URL` / `NEXT_PUBLIC_API_URL` | backend (client) | PUBLIC | same | same |
| `INTERNAL_PROXY_SECRET` | proxy auth | SECRET | **match backend** | (copy from Render) |
| `HMAC_SECRET` | callback signing | SECRET | **match backend** | (copy from Render) |
| `NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA` | router fallback | PUBLIC | Part 1 deploy output | `<FILL_AFTER_CONTRACT_DEPLOY>` |
| `NEXT_PUBLIC_TARGET_CHAIN_ID` | active chain | PUBLIC | — | `84532` |
| `ALLOWED_ORIGINS` | CORS for `/api/*` | PUBLIC | your Vercel URL | `https://<app>.vercel.app` |
| `NEXTAUTH_URL` / `NEXTAUTH_SECRET` | NextAuth | SECRET | self / `openssl rand -base64 32` | (optional testnet) |
| `ADMIN_SECRET` / `ADMIN_TOTP_SECRET` | admin dash | SECRET | `openssl rand -hex 32` / TOTP | (prod: required) |
