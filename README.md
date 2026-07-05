# RSends — Non-Custodial Crypto Payment Gateway

Accept stablecoin payments without ever giving up custody. Payments settle **directly
on-chain from the payer's wallet to the merchant's wallet**; a flat EUR-denominated fee
goes to the fee collector in the same transaction. RSends never holds funds and never
holds private keys — there is no hot wallet, no sweep, no custody path anywhere in the
system.

```
                    ┌──────────────────────┐
   payer wallet ───►│   RSendsRouter.sol   │───► merchant wallet   (amount − nothing withheld)
                    │  (pass-through only) │───► fee collector      (flat fee)
                    └──────────────────────┘
                               │ PaymentMade event
                               ▼
                     backend indexer ──► intent matched ──► signed webhook to merchant
```

## Monorepo layout

| Path | What it is |
|---|---|
| [`packages/contracts`](packages/contracts/) | Foundry project — `RSendsRouter.sol`, tests, deploy/config scripts |
| [`services/backend`](services/backend/) | Python FastAPI merchant API: payment intents, on-chain indexer, webhooks, auth, compliance |
| [`apps/web`](apps/web/) | Next.js 14 frontend: hosted checkout (`/pay`), merchant dashboard, docs site, landing |

Orchestrated with npm workspaces + Turbo; `make` targets wrap the common flows (see
[Local development](#local-development)).

## The contract — `RSendsRouter.sol`

[`packages/contracts/src/RSendsRouter.sol`](packages/contracts/src/RSendsRouter.sol) —
Solidity `^0.8.24`, OpenZeppelin v5 (`SafeERC20`, `ReentrancyGuard`, `Pausable`,
`Ownable2Step`).

- **Pass-through only.** Every payment is two direct transfers in one transaction:
  payer → merchant and payer → fee collector. The contract has no balance-holding logic;
  the owner can tune fee config and the collector address, **not** move or redirect
  merchant funds.
- `quoteFee(token, amount)` — view; what the frontend shows is what the chain charges.
- `pay(invoiceId, merchant, token, amount, maxFee)` — ERC-20 payment with a payer-side
  `maxFee` guard (no fee-config front-running).
- `payWithPermit(...)` — same flow with EIP-2612 permit, `try/catch` fallback for
  non-conforming tokens (USDT/DAI).
- `payNative(invoiceId, merchant, amount, maxFee)` — native ETH payment.
- Emits `PaymentMade(invoiceId, merchant, payer, token, amount, fee, blockTimestamp)` —
  the event the backend indexer settles against.

### Fee model

Flat, EUR-denominated per token, **never a percentage**, no price oracle:

| Payment amount | Fee |
|---|---|
| below €1,000 | **€0.60** flat |
| €1,000 and above | **€3.00** flat (cap) |

Single source of truth:
[`services/backend/app/token_registry.json`](services/backend/app/token_registry.json)
(per-token smallest-unit encodings for USDC / USDT / EURC / DAI), consumed by the
contract config script (`script/SetFeeConfig.s.sol`, which verifies `symbol()` /
`decimals()` on-chain before broadcasting), pinned by backend tests
(`tests/test_token_registry.py`), and rendered by the frontend pricing / checkout copy.
Native ETH is currently feeless (no oracle for a EUR peg).

## Backend — merchant API (`services/backend`)

FastAPI + SQLAlchemy 2 (async, PostgreSQL/asyncpg) + Redis + Celery. Python 3.12.

- **Payment intents** — merchants create intents (`pi_` + 128-bit CSPRNG id) with amount,
  currency, chain, expiry; the indexer matches confirmed `PaymentMade` events to intents.
- **On-chain indexer** (`app/services/payment_indexer.py`) — watches router events with
  configurable confirmation depth, finalized-tag support, and reorg detection
  (settlements carry block hash / reorg depth and can fire reversal webhooks —
  migrations 0002–0004).
- **Webhooks** — HMAC-SHA256 signed over `"{timestamp}.{body}"` with a per-merchant
  secret (`X-RSend-Signature` / `X-RSend-Timestamp`, 5-minute freshness window),
  delivered via Celery with retry.
- **API keys** — `rsend_test_` / `rsend_live_` Bearer keys, bcrypt-hashed at rest,
  scoped `read` / `write` / `admin`. Keys are environment-bound: test keys act only on
  testnet data, live keys only on mainnet — enforced on both reads and writes.
- **User auth** — email+password, Google, GitHub, and SIWE wallet sessions; JWT
  access/refresh with server-side sessions; **one account per normalized email**
  (collision on any second provider → 409 block-and-guide, never auto-linking; DB
  backstop via a `lower(email)` unique index).
- **Compliance & ops** — AML screening/admin surface, audit log, anomaly detection,
  circuit breakers, Prometheus metrics, Sentry, optional OpenTelemetry, structured JSON
  logging with correlation IDs.

### Security posture (enforced, audited 2026-07)

The full invariants live in [`CLAUDE.md`](CLAUDE.md) and are binding on every change.
Highlights:

- **Fail-closed rate limiting** on every public/mutating endpoint (Redis sliding window;
  Redis loss → 503, never fail-open). Unauthenticated endpoints limit per-IP.
- **Tenant isolation server-derived** — every query scoped by the `merchant_id` derived
  from the authenticated key, in the SQL itself; cross-tenant access returns **404**.
- **Environment binding** on intents and webhooks (test/live filtered on read, write,
  and outbound dispatch).
- **Public payer-facing surface is exactly one route** (`app/api/public_routes.py`):
  id-as-secret intent status, allowlisted fields only, read-only, per-IP rate limited.
- **Admin surface** (`/api/v1/audit`, `/admin/aml/*`, `/health/config`) gated by a
  dedicated `ADMIN_API_TOKEN` (constant-time compare, denies everything when unset).
- **Server-side validation always** — reject, never coerce; secrets in env only;
  production config guards refuse weak/placeholder secrets, non-TLS Redis, or dev
  bypass flags.

### Merchant API surface

Base `/api/v1/merchant`, Bearer API key:

| Method | Endpoint | Scope |
|---|---|---|
| POST | `/payment-intent` | write |
| GET | `/payment-intent/{id}` | read |
| GET | `/transactions` | read |
| POST | `/payment-intent/{id}/resolve` | write |
| POST | `/payment-intent/{id}/cancel` | write |
| POST | `/webhook/register` | write |
| POST | `/webhook/test` | write |
| POST | `/keys/generate`, `/keys/revoke` | admin |

Public (unauthenticated, what the hosted checkout polls):

| Method | Endpoint | Access model |
|---|---|---|
| GET | `/api/v1/public/payment-intent/{intent_id}` | id-as-secret; allowlisted status view; 20/min per IP |

Plus `/api/v1/auth/*` (login/signup/OAuth/SIWE/refresh), `/api/v1/user/*` (account,
sessions, devices, wallets, contacts, notifications), `/api/v1/organizations`,
`/api/v1/dashboard/stats`, `/api/v1/prices`, and `/health*` probes
(`/health`, `/live`, `/ready`, `/rpc`, `/dependencies`).

### Migrations

Linear Alembic chain, `0001` → `0007`:

| Rev | Purpose |
|---|---|
| 0001 | Non-custodial baseline schema |
| 0002 | Settlement fee tracking |
| 0003 | Settlement reorg fields |
| 0004 | Reversal-webhook state |
| 0005 | `PaymentIntent.environment` (test/live binding) |
| 0006 | `MerchantWebhook.environment` |
| 0007 | `lower(email)` unique index (one account per email) |

## Frontend (`apps/web`)

Next.js 14 (App Router) · React 18 · TypeScript · Tailwind · wagmi 2 + viem 2 +
RainbowKit · NextAuth (Google/GitHub bridge) · next-intl (**en, it, es, fr, de**).

- **Hosted checkout** — `/pay/[intentId]`: payer connects a wallet, sees the exact
  on-chain fee via `quoteFee`, pays through the router (permit flow where supported).
  Polls intent status through the public id-as-secret endpoint.
- **Merchant dashboard** — `/merchant/dashboard`: API keys, transactions, webhooks,
  invoices, settings (sessions/devices, sign-in methods, organizations, billing).
- **Docs site** — `/docs`: authentication, payment intents, hosted checkout, webhooks,
  refunds, reporting, testing; plus legal pages (privacy, terms, cookies, AML/KYC).
- **Server-side proxy** — the browser never talks to the backend directly:
  `app/api/backend/[...path]` and `app/api/rp-auth/[...path]` authenticate to the
  backend with a server-only `INTERNAL_PROXY_SECRET` (admin paths denylisted).
- Jest (jsdom) unit tests under `app/__tests__/`; `tsc --noEmit` gated in CI.

## Networks

| Chain | ID | Role |
|---|---|---|
| Base Sepolia | 84532 | `test` environment |
| Base Mainnet | 8453 | `live` |
| Ethereum Mainnet | 1 | `live` |

## Local development

One-command bootstrap — backend + frontend in development mode, no production-only
requirements (TLS Redis, real keys, OAuth consoles):

```bash
make setup    # one-time: 3.12 venv + deps + dev .env + Postgres/Redis + migrations
make dev      # backend (:8000) + frontend (:3000) together — Ctrl-C stops both
make dev-web  # frontend only, no infra needed
```

Prerequisites: **Python 3.12** (pinned in `services/backend/.python-version`;
`make setup` refuses anything else), **Node ≥ 20**, and Docker (or Homebrew
Postgres 16 + Redis).

`make setup` runs `scripts/gen_dev_env.py`, which generates gitignored dev env files
(`services/backend/.env`, `apps/web/.env.local`) with freshly generated matching
secrets. It is idempotent — existing files are never overwritten. Dev convenience comes
from the local `.env`, not from softening any production guard in `app/config.py`.

Other targets: `make dev-infra` (Postgres + Redis only), `make e2e-anvil` (full on-chain
money-path E2E on a local Anvil node), `make frontend-build` (the CI build gate),
`make check-python`.

### Contracts

```bash
cd packages/contracts
forge build && forge test
# fee/token policy: script/SetFeeConfig.s.sol (driven by token_registry.json)
```

## Testing & CI

CI (`.github/workflows/ci.yml`) runs four jobs:

1. **contracts** — `forge build --sizes` + `forge test -vvv`
2. **backend** — `pytest -m "not e2e and not integration"` on Python 3.12 (includes
   token-registry invariants and production-config hardening tests)
3. **frontend** — `tsc --noEmit` + `next build`
4. **e2e** — Anvil money-path: deploy the router, run the indexer, pay through both the
   permit (USDC) and approve (USDT) paths, assert settlement + webhook

Backend tests run against SQLite (`DATABASE_URL="sqlite+aiosqlite://" DEBUG=true
ENVIRONMENT=test`); frontend tests with `npx jest` from `apps/web`.

## Deployment

Production blueprint in [`render.yaml`](render.yaml) (Render, Frankfurt): managed
PostgreSQL, external TLS Redis, the FastAPI web service (always-on — it hosts the
indexer), a Celery worker (webhook/notify/analytics queues), and the Next.js site.
Production guards are active: `ENVIRONMENT=production`, `DEBUG=false`, TLS-only Redis,
mandatory `HMAC_SECRET` / `AUTH_JWT_SECRET` / `INTERNAL_PROXY_SECRET` /
`ADMIN_API_TOKEN` with length checks.

Operational docs: [`DEPLOY_RUNBOOK.md`](DEPLOY_RUNBOOK.md) — the single deploy +
go-live reference — and [`MIGRATION_REPORT.md`](MIGRATION_REPORT.md) (the
custodial → non-custodial migration record).

Fee-change deploys are ordered: **frontend copy first, on-chain `SetFeeConfig`
broadcast second**, so the displayed fee is never lower than the charged fee.

## License

Proprietary. All rights reserved.
