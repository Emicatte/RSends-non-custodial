# RSends Non-Custodial — Deploy Runbook (Base Sepolia / testnet · Part 6 = mainnet cutover)

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
   runs clean `0001 → 0007`. The old dev DB carried a **stale Classic stamp
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
| `AUTH_JWT_SECRET` ≥64 chars | ERROR | manual `token_hex(32)` |
| `ADMIN_API_TOKEN` non-empty/placeholder, ≥32 chars, ≠ `HMAC_SECRET` | ERROR | manual `openssl rand -hex 32` |
| `INTERNAL_PROXY_SECRET` non-empty | ERROR | Render `generateValue` |
| `WALLET_AUTH_ALLOW_LEGACY` not true | ERROR | `=false` |
| `DATABASE_URL` not localhost | WARNING | real host |
| `RSENDS_ROUTER_ADDRESSES_JSON` non-empty | WARNING | set after Part 1 |

**Lifespan assertions (`validate_dev_flags`):** `RSEND_DEV_AUTH_BYPASS` truthy
requires `ENVIRONMENT=development` (we never set it); `DEBUG=true` + `ENVIRONMENT`
prod → refuse start (we use `DEBUG=false`).

**Relaxed:** none of the security guards. The only non-security toggle is
`EMAIL_DEV_MODE=true` (outbound email off) — `APP_URL` is still required and set.
The one friction point is infra/setup, not a relaxation: Redis must be a TLS
(`rediss://`) endpoint.

---

## Order of operations

```
[1] Contract  → deploy RSendsRouter + SetFeeConfig on Base Sepolia   (gives router addr)
[2] Backend   → Render Blueprint (DB, Redis, web+indexer, worker, beat)
[3] Frontend  → Vercel (root = apps/web)
[4] Wire-up   → paste router addr + matching secrets across all three
[5] Smoke test
[6] Mainnet cutover (RouterV2) — LATER, gated on audit/MiCA/legal (Part 6)
```

---

## Part 1 — Contract on Base Sepolia (RUNBOOK — do not run from CI)

### Prerequisites **[AZIONE UTENTE]**
- **Foundry** installed (`foundryup`).
- **Build inputs are PINNED — do not override them.** `packages/contracts/foundry.toml` sets
  `solc_version = "0.8.36"` and `evm_version = "cancun"`, and the three production sources pin
  `pragma solidity 0.8.36;`. Run every build and deploy from `packages/contracts/` so that file
  applies, and do **not** pass `--use` / `--evm-version` or rely on a global Foundry profile.
  *Why:* these contracts are immutable, and solc's **default** EVM target moved twice in 2025
  (0.8.30 `cancun`→`prague`, 0.8.31 →`osaka`). Unpinned, two builds of the same commit can
  produce different bytecode and nobody can verify a deployed contract against this source.
  0.8.36 is the earliest release with no outstanding entry in the official Solidity bug list —
  0.8.28–0.8.33 carry a High-severity via-IR bug (SOL-2026-1) and this repo builds `via_ir`.
  `cancun` is the lowest target the whole build compiles on; `src/` alone would compile at
  `paris`, but the OZ `ERC20Permit` test mocks reach `mcopy`. Base has supported `cancun` since
  Ecotone (March 2024). The full reasoning is commented in `foundry.toml` itself.
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
Capture **`Deployed to: 0x…`** → **`<ROUTER_ADDRESS>`**, and the **deployment
block number** (from the `forge create` receipt, or look up the tx on BaseScan) →
**`<DEPLOY_BLOCK>`** (used as the indexer backfill safety-net in step 1d).

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

### 1d. Record the router address + indexer backfill safety-net **[AZIONE UTENTE]**
You'll paste `<ROUTER_ADDRESS>` into:
- backend `RSENDS_ROUTER_ADDRESSES_JSON={"84532":"<ROUTER_ADDRESS>"}`
- frontend `NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA=<ROUTER_ADDRESS>` — ⚠️ VESTIGIAL:
  zero consumers in `apps/web` (grep 2026-07-27); the checkout takes the router
  address + version from the backend `onchain` intent payload
  (`lib/web3/paymentIntent.ts`). Setting it is harmless but does nothing.

Also set the backend **`INDEXER_START_BLOCKS_JSON={"84532":"<DEPLOY_BLOCK>"}`**
(the router's deployment block from step 1b). This is a **safety-net**: if Redis
ever resets and the cursor is lost, the indexer backfills from the router's
deploy block instead of jumping to the current head — so the demo payment is
never missed. (Normal restarts still resume from the Redis cursor; this only
kicks in on a first run with no cursor.)

### 1e. Deploy the RSendsSplitRouter (split payments) **[AZIONE UTENTE]**
Ownerless + fee-less: no constructor args, no post-deploy config script (there
is no owner, pause, whitelist or fee to set — nothing to administer).
```bash
cd packages/contracts
forge script script/DeploySplitRouter.s.sol:DeploySplitRouter \
  --rpc-url "$BASE_SEPOLIA_RPC" \
  --account rsends-deployer \
  --broadcast
```
Capture the logged address → backend
`SPLIT_ROUTER_ADDRESSES_JSON={"84532":"<SPLIT_ROUTER_ADDRESS>"}`. No frontend
env: the /pay checkout receives the address via the backend `onchain` payload.
Until this var is set, split intent creation fail-closes with 422
`SPLIT_UNAVAILABLE` — deploying late is safe, deploying and not recording the
address just keeps splits disabled.

---

## Part 2 — Backend on Render (Blueprint)

### 2a. Create the Blueprint **[AZIONE UTENTE → AUTO]**
1. Push this repo to your private GitHub remote (see the separate push handover).
2. Render → **New → Blueprint** → pick the repo. Render reads [`render.yaml`](render.yaml)
   and provisions: `rsends-db` (Postgres), `rsends-redis`, `rsends-api` (web +
   indexer), and `rsends-worker` (Celery worker + embedded beat). **[AUTO]**

> **⚠️ Always-on tiers (required — NOT free).** The indexer runs inside the web
> service's lifespan, so `rsends-api` must never spin down. Minimum tiers:
> - `rsends-api`, `rsends-worker` → **Starter** (always-on; free web spins down
>   on idle = indexer stops; Render workers have no free tier).
> - `rsends-redis` → a **paid** plan **with persistence + `noeviction`** (the
>   indexer cursor lives in Redis; a wiped instance = a payment-detection gap).
> - `rsends-db` → paid (free Postgres expires after 30 days, no backups).
>
> **Worker + beat combined (demo/low-scale).** `rsends-worker` runs the worker
> **with the beat scheduler embedded** (`worker --beat`) as a single service, so
> there is **no separate `rsends-beat`**. It MUST stay `numInstances: 1` (a second
> instance = a second embedded beat = duplicate scheduled fires). **For
> production, re-split** into a dedicated worker + a separate single-instance beat.

### 2b. Fill the `sync: false` env vars **[AZIONE UTENTE]**
In the `rsends-shared` env group (Render dashboard):

| Var | Value |
|---|---|
| `DATABASE_URL` | Render `rsends-db` **Internal** URL, **scheme rewritten** to `postgresql+asyncpg://…` (no `rpagos:password@` default) |
| `REDIS_URL` | **TLS** `rediss://…/0` (prod guard rejects `redis://`) |
| `CELERY_BROKER_URL` | `rediss://…/1` |
| `CELERY_RESULT_BACKEND` | `rediss://…/2` |
| `AUTH_JWT_SECRET` | **manual** — `python -c 'import secrets;print(secrets.token_hex(32))'` (≥64 chars; Render's generated value may be too short) |
| `ADMIN_API_TOKEN` | **manual** — `openssl rand -hex 32` (≥32 chars, **must differ from `HMAC_SECRET`**; startup fails on empty/short/equal) |
| `ALCHEMY_API_KEY` | your Alchemy key (always required) |
| `RPC_PROVIDERS_JSON` | second RPC vendor — see **2b-ter** (unset = Alchemy + public fallbacks only, i.e. no paid redundancy) |
| `RSENDS_ROUTER_ADDRESSES_JSON` | `{"84532":"<ROUTER_ADDRESS>"}` (from Part 1) |
| `CORS_ORIGINS` / `APP_URL` | your Vercel URL, e.g. `https://<app>.vercel.app` |

`HMAC_SECRET` and `INTERNAL_PROXY_SECRET` are **[AUTO]** generated by Render —
copy both to Vercel (Part 4). `AUTH_JWT_SECRET` is **manual** (≥64 chars).
`ENVIRONMENT=production`, `DEBUG=false`, `WALLET_AUTH_ALLOW_LEGACY=false`,
`EMAIL_DEV_MODE=true` are set in the blueprint.

### 2b-bis. Redis setup (external TLS) **[AZIONE UTENTE]**
The prod guard requires `rediss://`, which is only available on Render Key
Value's **external** connection — so `REDIS_URL`/`CELERY_BROKER_URL`/
`CELERY_RESULT_BACKEND` are set **manually** (not auto-wired). Steps:
1. **Create the Key Value on a PAID plan** — persistence is required because the
   indexer cursor lives in Redis; free instances do **not** persist (a reset =
   a payment-detection gap).
2. Set **maxmemory policy = `noeviction`** (cursor/broker keys must never be
   evicted).
3. **Enable external access** and add to the **IP allowlist** your Render
   region's **static outbound IPs** (Render dashboard → service → Connect →
   Outbound). Without this the external `rediss://` connection is refused.
4. Copy the **external `rediss://` URL** and set `REDIS_URL` (`…/0`),
   `CELERY_BROKER_URL` (`…/1`), `CELERY_RESULT_BACKEND` (`…/2`). Downgrading to
   `redis://` is rejected at startup by design.

### 2b-ter. RPC failover — the second provider (QuickNode) **[AZIONE UTENTE]**

**Why this exists.** On 2026-08-22 the public `sepolia.base.org` returned
`-32011 no backend is currently healthy to serve traffic` for several minutes:
the indexer stopped detecting payments (122 failed ticks) and the hosted
checkout could not compute a fee, because `quoteFee` is a live `eth_call`.
Alchemy — the other provider — had been quota-exhausted for *days* and nobody
knew. One vendor down should be a non-event; it was an outage because there was
effectively only one vendor.

**`RPC_PROVIDERS_JSON` is NOT declared in `render.yaml`** (same treatment as
`RSENDS_ROUTER_V2_ADDRESSES_JSON`): add it by hand in the Render dashboard →
service → *Environment* → *Add Environment Variable*. Mark it **secret** — the
QuickNode URL contains the token.

Value (**one line**, placeholders only — never commit the real endpoint):

```json
{"84532":[{"name":"quicknode","url":"https://<YOUR-QUICKNODE-SUBDOMAIN>.base-sepolia.quiknode.pro/<YOUR-QUICKNODE-TOKEN>/"}],"8453":[{"name":"quicknode","url":"https://<YOUR-QUICKNODE-SUBDOMAIN>.base-mainnet.quiknode.pro/<YOUR-QUICKNODE-TOKEN>/"}]}
```

Schema: `{ "<chain_id>": [ {"name": …, "url": …, "priority"?: int} ] }`.
`priority` is optional and defaults to `0`, which is what you want: the vendor
lands **after Alchemy (-1) and before the public fallbacks**. Set the mainnet
(`8453`) entry now even though mainnet is not live — it costs nothing and
removes a step from the Part 6 cutover. Malformed input is ignored with a
startup warning and never blocks boot, so a typo degrades you back to one
vendor *silently as far as traffic is concerned* — which is exactly why the
verification below is not optional.

> **The two providers must be different vendors — not two keys from one.**
> Everything that killed Alchemy here is per-*account* or per-*vendor*: a
> monthly compute quota, a lapsed card, a rotated key, a fleet-wide incident. A
> second Alchemy key shares the quota, the billing relationship and the
> infrastructure, so it fails at the same instant as the first and buys nothing.
> The public `sepolia.base.org` / `mainnet.base.org` endpoints stay in the list
> as a best-effort third leg — they are **not** redundancy: the public endpoint
> is the one that went down on 2026-08-22.

**Verify after the deploy — do not assume.** Two independent checks:

1. The provider list actually contains both vendors:
   ```bash
   curl -s https://rsends-non-custodial.onrender.com/health/rpc \
     | jq '.base_sepolia.providers'
   ```
   `/health/rpc` is unauthenticated and returns names/health/block/circuit
   state — never URLs, so no token leaks. Expect, **in this order**:
   ```json
   [{"name":"alchemy","healthy":true,"last_block":12345678,"circuit_state":"closed"},
    {"name":"quicknode","healthy":true,"last_block":12345678,"circuit_state":"closed"},
    {"name":"base_sepolia","healthy":true,"last_block":12345678,"circuit_state":"closed"}]
   ```
   `quicknode` **present** proves it is in the failover list;
   `last_block > 0` proves the health loop got a real answer out of it — a
   wrong URL or a bad token shows up as `last_block: 0` with `healthy: false`.
   Only two entries → the variable was not picked up (check for a stray
   newline; Render keeps multi-line values verbatim).
2. The boot log (Render → *Logs*) states the inventory on every start:
   ```
   RPC providers chain=84532 (3): alchemy, quicknode, base_sepolia
   ```
   There must be **no** `RPC chain 84532 has NO REDUNDANCY` warning. If a
   provider later dies, the log carries a matching
   `RPC provider <name> LOST on chain 84532 (…) — N of M providers still
   serving` at ERROR, and an `RPC_DOWN` alert goes to Telegram once
   `TELEGRAM_CHAT_ID` is set.

### 2c. Deploy **[AUTO]**
Render runs `preDeployCommand: alembic upgrade head` then starts the services.
Migrations use Alembic's **async** engine (`async_engine_from_config`) reading
`DATABASE_URL` directly — so the **same `postgresql+asyncpg://` URL works for
migrations**; there is **no** separate sync/psycopg2 URL to configure (psycopg2
isn't even installed). On the empty Render DB this runs clean `0001 → 0007`.
Confirm `https://rsends-non-custodial.onrender.com/health` returns `{"status":"healthy"}`.

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
1. `GET https://rsends-non-custodial.onrender.com/health` → `healthy`.
2. Render `rsends-api` logs show the indexer started for chain `84532`.
3. Open the Vercel app → create a payment intent → the `/pay/[intentId]` page
   loads and reads the router address from the intent.
4. Pay with a Base Sepolia testnet wallet (USDC `0x036CbD…` or native ETH);
   confirm the indexer picks up `PaymentMade` and the intent settles.
5. Confirm a merchant webhook is delivered (the embedded beat's 15s loop inside
   `rsends-worker` → worker delivery).

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
re-deploy re-runs `upgrade head`, which is a no-op once at `0007`.

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
| `ADMIN_API_TOKEN` | admin surface bearer (≥32, ≠ `HMAC_SECRET`) | SECRET | **manual** `openssl rand -hex 32` | (64-char hex) |
| `ALCHEMY_API_KEY` | RPC (always required) | SECRET | dashboard.alchemy.com | `<alchemy_key>` |
| `RSENDS_ROUTER_ADDRESSES_JSON` | chain→router map (v1) | PUBLIC | Part 1 deploy output | `{"84532":"<FILL_AFTER_CONTRACT_DEPLOY>"}` |
| `RSENDS_ROUTER_V2_ADDRESSES_JSON` | chain→RouterV2 map — **the mainnet cutover** (Part 6) | PUBLIC | Part 6 deploy output; **manual on Render: NOT in `render.yaml`**, the blueprint will never carry it | unset until cutover |
| `RPC_PROVIDERS_JSON` | second RPC vendor, chain→list (**§2b-ter**) | SECRET (holds the endpoint token) | QuickNode dashboard; **manual on Render: NOT in `render.yaml`** | `{"84532":[{"name":"quicknode","url":"https://<SUB>.base-sepolia.quiknode.pro/<TOKEN>/"}]}` |
| `CORS_ORIGINS` / `APP_URL` | allowed origins / public URL | PUBLIC | your Vercel URL | `https://<app>.vercel.app` |
| `ENVIRONMENT` / `DEBUG` | guard posture | PUBLIC | `production` / `false` (in blueprint) | — |
| `WALLET_AUTH_ALLOW_LEGACY` | anti-replay guard | PUBLIC | `false` (in blueprint) | `false` |
| `EMAIL_DEV_MODE` | outbound email off | PUBLIC | `true` (in blueprint) | `true` |

### Frontend (Vercel)
| Name | What | Class | Where to get it | Placeholder |
|---|---|---|---|---|
| `NEXT_PUBLIC_WC_PROJECT_ID` | WalletConnect | PUBLIC | cloud.walletconnect.com | `<wc_project_id>` |
| `RPAGOS_BACKEND_URL` | backend (server) | PUBLIC | Render web URL | `https://rsends-non-custodial.onrender.com` |
| `NEXT_PUBLIC_RPAGOS_BACKEND_URL` / `NEXT_PUBLIC_API_URL` | backend (client) | PUBLIC | same | same |
| `INTERNAL_PROXY_SECRET` | proxy auth | SECRET | **match backend** | (copy from Render) |
| `HMAC_SECRET` | callback signing | SECRET | **match backend** | (copy from Render) |
| `NEXT_PUBLIC_RSENDS_ROUTER_BASE_SEPOLIA` | ⚠️ vestigial — zero consumers (see 1d) | PUBLIC | Part 1 deploy output | `<FILL_AFTER_CONTRACT_DEPLOY>` |
| `NEXT_PUBLIC_TARGET_CHAIN_ID` | active chain | PUBLIC | — | `84532` |
| `ALLOWED_ORIGINS` | CORS for `/api/*` | PUBLIC | your Vercel URL | `https://<app>.vercel.app` |
| `NEXTAUTH_URL` / `NEXTAUTH_SECRET` | NextAuth | SECRET | self / `openssl rand -base64 32` | (optional testnet) |
| `ADMIN_SECRET` / `ADMIN_TOTP_SECRET` | admin dash | SECRET | `openssl rand -hex 32` / TOTP | (prod: required) |

---

## Go-live / external provisioning

One-time provisioning that no deploy step above covers — do these before (or
with) the first production-posture deploy:

1. **`ADMIN_API_TOKEN` (Render, backend).** The admin surface
   (`GET /api/v1/audit/log`, `/admin/aml/*`, `GET /health/config`) authenticates
   with the `X-Admin-Token` header equal to this **dedicated** env var —
   constant-time compare, denies everything when unset, and it is **not**
   `HMAC_SECRET` (reusing it is rejected). The prod guard fails startup on
   empty/placeholder, <32 chars, or `== HMAC_SECRET` (`app/config.py`).
   Generate with `openssl rand -hex 32`. Verify after deploy:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://rsends-non-custodial.onrender.com/health/config
   # → 403 (anonymous denied)
   curl -s -o /dev/null -w "%{http_code}\n" \
     -H "X-Admin-Token: <ADMIN_API_TOKEN>" https://rsends-non-custodial.onrender.com/health/config
   # → 200 (env var audit; values never exposed)
   ```
2. **Monitoring (optional).** Backend env: `SENTRY_DSN` (errors),
   `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` / `TELEGRAM_ALERT_CHAT_ID`
   (alerts), `ALERT_WEBHOOK_URL` (Slack/Discord webhook).

---

## Part 6 — Mainnet cutover (RSendsRouterV2) **[DO NOT RUN before prerequisites]**

The mainnet router is `RSendsRouterV2` — ownerless, fee-less, single-transfer
(payer → merchant, full amount; see `packages/contracts/AUDIT_HANDOFF_ROUTERV2.md`).
Everything above this section deploys the **testnet/v1** stack and stays untouched:
the cutover ADDS a v2 chain next to it. Written 2026-07-27, while the RPagos audit
window is open — review this section against the code again if the cutover happens
after further backend changes.

### 6.0 Prerequisites **[GATE — all three, no exceptions]**
- **RPagos internal audit verdict** on PR #73 / `AUDIT_HANDOFF_ROUTERV2.md`.
- **MiCA written opinion** in hand.
- **Terms §6 legal pass done** — the "subscription-only" sentence must be updated
  BEFORE real-money traffic (the "nothing deducted from settlements" sentence is
  accurate as-is: v2 is a single full-amount transfer, and even v1 pays the fee
  payer-side — `src/RSendsRouter.sol:72-73`).

### 6a. Deploy `RSendsRouterV2` on mainnet **[AZIONE UTENTE]**
No constructor args, no owner, nothing to configure after deploy.

**Before broadcasting — confirm the build is the pinned, reproducible one.** This is the last
moment it can be checked; after the deploy the bytecode is immutable forever.
```bash
cd packages/contracts
forge clean && forge build          # run twice; the hash below must not change
python3 -c "import json;from eth_utils import keccak;d=json.load(open('out/RSendsRouterV2.sol/RSendsRouterV2.json'));print(d['metadata']['compiler']['version'], d['metadata']['settings']['evmVersion']);print('0x'+keccak(bytes.fromhex(d['deployedBytecode']['object'][2:])).hex())"
```
Expected, as of the pin (`chore/pin-solc-evm-target`):
`0.8.36+commit.8a079791`, `cancun`, runtime keccak
`0xc9f741a0bcce7e051a91d66a09c3b42edfd4b7efa346e200267c40af0ac8dd5b`.
A different hash means the source, the compiler or the EVM target changed — find out which
**before** deploying, do not proceed and reconcile afterwards.

```bash
cd packages/contracts
forge script script/DeployRouterV2.s.sol:DeployRouterV2 \
  --rpc-url https://mainnet.base.org --account rsends-deployer --broadcast
```
Capture the deployed address → **`<ROUTER_V2_ADDRESS>`** and the **deployment
block number** → **`<V2_DEPLOY_BLOCK>`**.

### 6b. ⚠️ Do NOT run `SetFeeConfig.s.sol` against v2 **[NON-STEP]**
`script/SetFeeConfig.s.sol` is **v1-only**. v2 has no fee config and no owner —
any such call reverts (`token_registry.json` `_comment` documents the same). The
registry fee keys (`flatFee`/`threshold`/`aboveFee`) are ignored on v2 chains;
the backend reads only enabled/permit/identity there. There is no on-chain
config step for v2. Skipping this is the point.

### 6c. Backend env cutover **[AZIONE UTENTE — manual on Render dashboard]**
```
RSENDS_ROUTER_V2_ADDRESSES_JSON={"8453":"<ROUTER_V2_ADDRESS>"}
```
- **This env var is NOT in `render.yaml`** — the blueprint will never carry it.
  Set it by hand on the `rsends-shared` env group (this is deliberate: the
  blueprint stays testnet-complete, the cutover is an explicit manual act).
- A chain in this map creates **v2 intents**; v2 **wins over v1** if both are
  set for the same chain; the indexer watches v1 and v2 **side by side**, so
  in-flight v1 payments still settle (`app/config.py:57-62`,
  `router_registry.py`).
- Also extend `INDEXER_START_BLOCKS_JSON` with `"8453":"<V2_DEPLOY_BLOCK>"` —
  same Redis-cursor-loss safety-net as step 1d, for the new chain.
- Rollback = remove the map entry (intent creation falls back to whatever v1
  serves; v2 has no state to unwind — it never holds balance).

### 6d. Frontend: nothing to set **[NO ACTION]**
The `/pay` checkout receives the router **address and version** from the backend
`onchain` intent payload (`apps/web/lib/web3/paymentIntent.ts` — `router`,
`routerVersion`; the v2 ABI ships in `apps/web/lib/rsendsRouterV2Abi.ts`). No
`NEXT_PUBLIC_*` router var exists for v2 and none is needed (the Sepolia one in
Part 3b is vestigial, see 1d).

### 6e. Copy flip — the zero-fee claims become present-tense **[AZIONE UTENTE → PR]**
PR #75 (2026-07-25) made every zero-fee claim conditional ("from mainnet
launch"). At cutover those claims flip to true and the conditional wording must
go. Surfaces (all 5 locales, from the PR #75 body):
- `hero.subtitle` (landing), `twoPaths.businesses.body` (landing)
- `pricing.faq.items[1].a` ("Is there a per-transaction fee?")
- `app/[locale]/pricing/page.tsx` hardcoded SEO meta description (EN-only)

Ship as a PR in the same window as 6c; the copy-pinning jest test
(`app/__tests__/marketing/localeKeys.test.ts`) must move in the same PR.

### 6f. Post-cutover verification **[AZIONE UTENTE]**
1. `GET /health` → the new chain id appears in `indexer` with `lag` sane.
2. Create a real payment intent on chain 8453 and pay a minimal amount from a
   real wallet: assert the merchant receives the **full** amount, the settlement
   records `fee 0`, and the signed webhook arrives (this is the production
   mirror of `tests/e2e/test_money_path_anvil_v2.py`).
3. Registry coverage caveat: the scheduled **`onchain-verify` workflow covers v1
   chains only** — its parity check reconstructs the enabled set from
   `FeeConfigSet` logs, which v2 never emits, and it keys off
   `RSENDS_ROUTER_ADDRESSES_JSON` (the v1 secret). Do **not** add the v2 address
   to that secret (the parity check would false-alarm). Accepted consequence:
   v2 chains get no scheduled on-chain cross-check — there is no on-chain config
   to drift; token enable/disable for v2 chains is backend-side only
   (`token_registry.json` + creation gate, `tests/test_creation_token_gate.py`).
   If symbol/decimals cross-checking for the v2 chain is ever wanted, that is a
   small code change to `scripts/verify_onchain_registry.py`, out of scope here.
