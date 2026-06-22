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
2. **True-prod guard posture.** This deploy runs `ENVIRONMENT=production` +
   `DEBUG=false`, so **every** prod guard in `config.py` is active. We satisfy
   all of them — **no security guard is relaxed** (see "Prod guards" below). The
   only non-security toggle is outbound email off (`EMAIL_DEV_MODE=true`).
3. **Keys never touch the repo.** The deployer/owner private key lives in a
   Foundry keystore (`cast wallet import`) — never in env, a committed file, a
   command, or a log. `SetFeeConfig.s.sol` signs via `--account` (keystore).

---

## Prod guards (everything `is_prod=true` gates)

`is_prod = (not DEBUG) or ENVIRONMENT startswith "prod"`. With our posture
(`ENVIRONMENT=production`, `DEBUG=false`) `is_prod` is **true**. Full list from
`config.py` and how each is satisfied here:

**Always enforced (any posture) — ERROR = startup blocked:**
| Guard | Severity | How we satisfy it |
|---|---|---|
| `ALCHEMY_API_KEY` non-empty | ERROR | real Alchemy key |
| `APP_URL` set + non-localhost (if prod *or* email on) | ERROR | Vercel URL |

**Enforced only when `is_prod` — ERROR unless noted:**
| Guard | Severity | How we satisfy it |
|---|---|---|
| `HMAC_SECRET` not placeholder & ≥32 chars | ERROR | Render `generateValue` |
| `REDIS_URL` must be `rediss://` (TLS) | ERROR | TLS Redis endpoint |
| `CELERY_BROKER_URL` must be `rediss://` (TLS) | ERROR | TLS Redis endpoint |
| no `rpagos:password@` default DB creds | ERROR | real DB creds |
| `DEBUG` must not be true | ERROR | `DEBUG=false` |
| `GOOGLE_OAUTH_CLIENT_ID` non-empty | ERROR | Google OAuth client |
| `AUTH_JWT_SECRET` ≥64 chars | ERROR | manual `token_hex(32)` |
| `INTERNAL_PROXY_SECRET` non-empty | ERROR | Render `generateValue` |
| `WALLET_AUTH_ALLOW_LEGACY` not true | ERROR | `=false` |
| `DATABASE_URL` not localhost | WARNING | real host |
| `RSENDS_ROUTER_ADDRESSES_JSON` non-empty | WARNING | set after Part 1 |

**Lifespan assertions (`validate_dev_flags`):** `RSEND_DEV_AUTH_BYPASS` truthy
requires `ENVIRONMENT=development` (we never set it); `DEBUG=true` + `ENVIRONMENT`
prod → refuse start (we use `DEBUG=false`).

**Relaxed:** none of the security guards. The only non-security toggle is
`EMAIL_DEV_MODE=true` (outbound email off) — `APP_URL` is still required and set.
The two friction points are infra/setup, not relaxations: Redis must be a TLS
(`rediss://`) endpoint, and a Google OAuth client must exist (free, works on a
`vercel.app` domain).

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

This script signs with a **Foundry keystore account** (`vm.startBroadcast()` — no
private key in env or CLI). The `--account` you pass **must be the router
`OWNER`**. If `OWNER` == the deployer from step 1a, reuse `rsends-deployer`;
otherwise import the owner's key as its own keystore (`cast wallet import
rsends-owner --interactive`) and use that.
```bash
cd packages/contracts
ROUTER_ADDRESS=<ROUTER_ADDRESS> \
forge script script/SetFeeConfig.s.sol:SetFeeConfig \
  --rpc-url "$BASE_SEPOLIA_RPC" \
  --account rsends-deployer \
  --broadcast
# ROUTER_ADDRESS is a public address (not a secret). No PRIVATE_KEY is exported.
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

> **⚠️ Always-on tiers (required — NOT free).** The indexer runs inside the web
> service's lifespan, so `rsends-api` must never spin down. Minimum tiers:
> - `rsends-api`, `rsends-worker`, `rsends-beat` → **Starter** (always-on; free
>   web spins down on idle = indexer stops; Render workers have no free tier).
> - `rsends-redis` → a plan **with persistence + `noeviction`** (the indexer
>   cursor lives in Redis; a wiped instance = a payment-detection gap).
> - `rsends-db` → paid (free Postgres expires after 30 days, no backups).

### 2b. Fill the `sync: false` env vars **[AZIONE UTENTE]**
In the `rsends-shared` env group (Render dashboard):

| Var | Value |
|---|---|
| `DATABASE_URL` | Render `rsends-db` **Internal** URL, **scheme rewritten** to `postgresql+asyncpg://…` (no `rpagos:password@` default) |
| `REDIS_URL` | **TLS** `rediss://…/0` (prod guard rejects `redis://`) |
| `CELERY_BROKER_URL` | `rediss://…/1` |
| `CELERY_RESULT_BACKEND` | `rediss://…/2` |
| `AUTH_JWT_SECRET` | **manual** — `python -c 'import secrets;print(secrets.token_hex(32))'` (≥64 chars; Render's generated value may be too short) |
| `GOOGLE_OAUTH_CLIENT_ID` | **required** — create a Google OAuth client (free; works on `vercel.app`) |
| `ALCHEMY_API_KEY` | your Alchemy key (always required) |
| `INDEXER_RPC_URLS_JSON` | `{"84532":"https://base-sepolia.g.alchemy.com/v2/<KEY>"}` |
| `RSENDS_ROUTER_ADDRESSES_JSON` | `{"84532":"<ROUTER_ADDRESS>"}` (from Part 1) |
| `CORS_ORIGINS` / `APP_URL` | your Vercel URL, e.g. `https://<app>.vercel.app` |

`HMAC_SECRET` and `INTERNAL_PROXY_SECRET` are auto-generated by Render — copy
both to Vercel (Part 4). `ENVIRONMENT=production`, `DEBUG=false`,
`WALLET_AUTH_ALLOW_LEGACY=false`, `EMAIL_DEV_MODE=true` are set in the blueprint.

> **Redis TLS note.** The prod guard requires `rediss://`. Render Key Value:
> use its TLS connection string. If your instance only exposes internal
> `redis://`, use an external TLS Redis (e.g. Upstash free → `rediss://`).
> Downgrading to `redis://` is rejected at startup by design.

`HMAC_SECRET` and `INTERNAL_PROXY_SECRET` are **[AUTO]** generated by Render —
copy both to Vercel (Part 4). `AUTH_JWT_SECRET` is **manual** (≥64 chars).

### 2c. Deploy **[AUTO]**
Render runs `preDeployCommand: alembic upgrade head` then starts the services.
Migrations use Alembic's **async** engine (`async_engine_from_config`) reading
`DATABASE_URL` directly — so the **same `postgresql+asyncpg://` URL works for
migrations**; there is **no** separate sync/psycopg2 URL to configure (psycopg2
isn't even installed). On the empty Render DB this runs clean `0001 → 0004`.
Confirm `https://rsends-api.onrender.com/health` returns `{"status":"healthy"}`.

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

## Restart-safety & migrations (verified)

**Indexer cursor (restart-safe via Redis).** The indexer persists the last
processed block in **Redis**, key `indexer:last_block:{chain_id}`
(`payment_indexer.py` `_get_last_block`/`_set_last_block`). On (re)start it reads
the cursor and resumes from `min(last+1, head+1)`, re-checking the last
`INDEXER_REORG_SAFETY_DEPTH` finalized blocks for reorgs. So a **Render web
redeploy/restart resumes cleanly** — no rescan from zero, no missed blocks.

> **⚠️ The cursor is only as durable as Redis.** On **first run with no cursor**
> the indexer starts at the **current head** (`max(final_head, 0)`), not block 0.
> That means if Redis ever **loses** the key (eviction, or a wiped free-tier
> instance), the next start jumps forward and **skips the gap → missed
> payments** (it does NOT re-scan from zero). Mitigations, all applied/available:
> - Redis plan **with persistence** + `maxmemoryPolicy: noeviction` (in
>   `render.yaml`) so the key survives restarts and memory pressure.
> - To recover after a known loss, set `INDEXER_START_BLOCKS_JSON={"84532":"<block>"}`
>   to the last-known-good block and restart (forces a backfill from there).

**Migrations (asyncpg, no sync URL).** `alembic upgrade head` (in
`preDeployCommand`) uses Alembic's async engine reading `DATABASE_URL` directly —
the same `postgresql+asyncpg://` URL the app uses. There is **no** psycopg2/sync
URL to provide (psycopg2 is not installed). Idempotent across restarts: a
re-deploy re-runs `upgrade head`, which is a no-op once at `0004`.

---

## Master ENV checklist

**SECRET** = dashboard only, never in the repo. **PUBLIC** = safe to expose.

### Backend (Render `rsends-shared`)
| Name | What | Class | Where to get it | Placeholder |
|---|---|---|---|---|
| `DATABASE_URL` | Postgres DSN (asyncpg) | SECRET | Render DB Internal URL, scheme `+asyncpg` | `postgresql+asyncpg://u:p@host:5432/rsends` |
| `REDIS_URL` | cache/idempotency/cursor | SECRET | TLS Redis URL `/0` | `rediss://host:6379/0` |
| `CELERY_BROKER_URL` | Celery broker | SECRET | TLS Redis URL `/1` | `rediss://host:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery results | SECRET | TLS Redis URL `/2` | `rediss://host:6379/2` |
| `HMAC_SECRET` | inbound callback HMAC (≥32) | SECRET | Render generateValue | (auto) |
| `INTERNAL_PROXY_SECRET` | gates `/api/internal/*` | SECRET | Render generateValue | (auto) |
| `AUTH_JWT_SECRET` | session JWT (≥64) | SECRET | **manual** `token_hex(32)` | (64-char hex) |
| `GOOGLE_OAUTH_CLIENT_ID` | Google login (**required**) | SECRET | Google Cloud Console | `<oauth_client_id>` |
| `ALCHEMY_API_KEY` | RPC (always required) | SECRET | dashboard.alchemy.com | `<alchemy_key>` |
| `RSENDS_ROUTER_ADDRESSES_JSON` | chain→router map | PUBLIC | Part 1 deploy output | `{"84532":"<FILL_AFTER_CONTRACT_DEPLOY>"}` |
| `INDEXER_RPC_URLS_JSON` | chain→RPC map | SECRET (has key) | Alchemy | `{"84532":"https://base-sepolia.g.alchemy.com/v2/<KEY>"}` |
| `CORS_ORIGINS` / `APP_URL` | allowed origins / public URL | PUBLIC | your Vercel URL | `https://<app>.vercel.app` |
| `ENVIRONMENT` / `DEBUG` | guard posture | PUBLIC | `production` / `false` (in blueprint) | — |
| `WALLET_AUTH_ALLOW_LEGACY` | anti-replay guard | PUBLIC | `false` (in blueprint) | `false` |
| `EMAIL_DEV_MODE` | outbound email off | PUBLIC | `true` (in blueprint) | `true` |

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
