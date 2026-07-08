# RSends (non-custodial)

Monorepo for a non-custodial crypto payment platform:
- `apps/web` — Next.js frontend (checkout, dashboard, docs site)
- `services/backend` — Python FastAPI merchant API
- `packages/contracts` — Solidity contracts (Foundry): immutable fee router

## Security

These rules reflect the verified state of the backend security audit (2026-07). Apply them to
**every change**. If code and this document ever diverge, the code is the source of truth —
flag the divergence and update this file in the same review.

### Security invariants (apply to every change)

- **Non-custodial is absolute.** RSends never holds funds or private keys. Never add a code path
  where the platform custodies, sweeps, or moves user funds. On-chain settlement goes
  payer → merchant / fee → fee collector via the immutable router only.
- **Rate limiting on every public/mutating endpoint.** Backend merchant routes are enforced by
  the Redis sliding-window middleware with per-endpoint rules
  (`services/backend/app/middleware/rate_limit.py`, `ENDPOINT_LIMITS`). It is **fail-closed**:
  Redis loss → 503 `RATE_LIMIT_UNAVAILABLE`, never fail-open. Unauthenticated/public endpoints
  (tx callback, auth, user routes, public checkout polling) rate-limit **per-IP** — auth-based
  limits don't apply when there's no key. New endpoints must get an `ENDPOINT_LIMITS` entry.
- **Server-side validation always.** Validate & **reject** (never coerce) on the server even if
  the client also validates. Bounded lengths, whitelisted enums, address regex
  `^0x[a-fA-F0-9]{40}$` (`services/backend/app/security/input_validator.py`).
- **Secrets in env only.** No key/secret/token literal in code or client bundles. API keys and
  signing secrets live server-side; never ship a secret to the browser. `.env.example` holds
  placeholders; real `.env*` files are gitignored and must stay untracked.
- **Tenant isolation is server-derived.** Scope every query by a `merchant_id` derived from the
  authenticated API key (`request.state.client`), never from a client-supplied parameter. The
  ownership filter belongs **in the SQL/query**, not a post-fetch `if`. Cross-tenant access must
  return **404, not 403** (don't leak existence).
- **Environment binding.** `rsend_test_` keys act only on testnet/test data; `rsend_live_` only
  on mainnet/live. Filter **both reads and writes** by the key's environment: intents carry
  `PaymentIntent.environment` (stamped at create, filtered on get/list/resolve/cancel via
  `_get_environment(request)`), webhooks carry `MerchantWebhook.environment` (stamped at
  register, filtered on lookup AND outbound dispatch by `intent.environment`). Any new
  merchant-scoped table needs the same column + filters.
- **Webhook trust.** Outbound webhooks are signed HMAC-SHA256 over `"{timestamp}.{body}"` with a
  per-merchant secret, headers `X-RSend-Signature` / `X-RSend-Timestamp`, 5-minute freshness
  window (`services/backend/app/services/webhook_service.py`). Consumers must verify before
  trusting. This is the **only** signing scheme — do not introduce another.
- **Fail closed.** Auth/isolation fallbacks must deny (401/404), never fall into a shared or
  default bucket. `_get_merchant_id` raises 401 when there is no authenticated client; **no
  merchant route is public**. The only sanctioned unauthenticated read is the dedicated
  payer-facing view in `app/api/public_routes.py` (see below).
- **One account per email (user auth).** Emails are normalized (`lower().strip()`) on EVERY
  auth ingest path (email/password schemas, Google, GitHub) and again in the login handlers;
  every entry path guards collisions — a second provider hitting an existing email gets
  **409 `email_already_registered` (block-and-guide** via `AccountLinkingModal`), never a
  second account and **never auto-linking** (explicit settings-page linking is the only merge
  path). DB backstop: unique index `uq_users_email_lower` on `lower(email)` (User
  `__table_args__` + migration 0007 — which reports-and-stops on pre-existing duplicates,
  never auto-merges). The Google email-change sync also refuses to overwrite into a collision.
- **Public (payer-facing) endpoints live in `app/api/public_routes.py` only.** Trust boundary
  rules for anything added there: access model is **id-as-secret** (the lookup key must be
  ≥128-bit CSPRNG, e.g. `intent_id = "pi_" + secrets.token_hex(16)`); single-object lookups
  only (no lists/filters — nothing enumerable); serialize an explicit allowlisted Pydantic
  model, never the ORM object; read-only (no DB writes); per-IP rate limited; 404 on miss.
  Must work in production config — never rely on `RSEND_DEV_AUTH_BYPASS`.

### Access-control matrix

**Identity.** API key (Bearer) → `client_id = owner_address = merchant_id`
(`app/middleware/api_auth.py`, `app/security/api_keys.py`). Keys are `rsend_{test|live}_` + hex,
bcrypt-hashed at rest, plaintext shown once at creation.

**Scopes.** `read` | `write` | `admin`. Enforcement is method-based in the auth middleware: any
non-GET request with a `read` key → 403 `INSUFFICIENT_SCOPE`. `/api/v1/keys/generate` and
`/api/v1/keys/revoke` additionally require `admin` (403 `ADMIN_REQUIRED` otherwise).

**Environments.** `test` (Base Sepolia) vs `live` (mainnet, per jurisdiction). A key must act
only within its environment; per-route enforcement is in the table below.

**Per-resource rule.** A merchant may read/mutate **only** objects where
`merchant_id == self`; anything else → 404.

Merchant routes (base `/api/v1/merchant`, defined in `app/api/merchant_routes.py`):

| Route | Required scope | Environment-scoped | Tenant-scoped |
|---|---|---|---|
| `POST /payment-intent` (create) | write | Y — chain↔env check + env stamped on the intent | Y — **recipient gate**: resolves override → org `settlement_wallet`; 422 if unresolvable |
| `GET /payment-intent/{id}` | read | Y — `PaymentIntent.environment` filter | Y |
| `GET /transactions` (list) | read | Y — `PaymentIntent.environment` filter | Y |
| `POST /payment-intent/{id}/resolve` | write | Y — `PaymentIntent.environment` filter | Y |
| `POST /payment-intent/{id}/cancel` | write | Y — `PaymentIntent.environment` filter | Y |
| `POST /webhook/register` | write | Y — env stamped on the webhook | Y |
| `POST /webhook/test` | write | Y — `MerchantWebhook.environment` filter | Y |

Outbound webhook dispatch (`webhook_service.py`) also filters
`MerchantWebhook.environment == intent.environment` — test endpoints never receive live
events and vice versa.

**Recipient gate (non-custodial invariant, Phase B).** A `PaymentIntent` **cannot** be
created without a resolvable on-chain recipient — the single construction site
(`merchant_routes.py`, one `PaymentIntent(...)`) calls `resolve_recipient`
(`app/services/intent_service.py`) first: per-intent override (Pydantic-validated) →
else the org's `settlement_wallet` (session path by `org_id`; API-key path by reverse
lookup of the owner wallet → its org). Fail-closed **422** when unresolvable
(`SETTLEMENT_WALLET_MISSING`) or when the owner wallet maps to >1 org
(`SETTLEMENT_WALLET_AMBIGUOUS`) — never silently default a recipient. `settlement_wallet`
is an org-level column (admin-set in Settings via `PATCH /api/v1/organizations/{id}`,
replace-only, EVM-address + non-zero validated, stored lowercase; migration 0008, nullable,
no backfill). The indexer (`payment_indexer.py`) now records a settlement **rejected** when a
matched intent has no recipient (was a silent skip) — a legacy pre-gate row can't settle
against an arbitrary payee.

Public (unauthenticated, payer-facing) surface — `app/api/public_routes.py`:

| Route | Auth | Access model | Rate limit |
|---|---|---|---|
| `GET /api/v1/public/payment-intent/{intent_id}` | none | id-as-secret (128-bit CSPRNG id); limited allowlisted view: `status, amount, currency, chain, expires_at, merchant_name, tx_hash, onchain`; read-only; 404 on miss | 20/min **per IP** |

This is what the hosted checkout `/pay` polls (via `apps/web/app/api/pay/[intentId]/route.ts`).
The merchant GET is fully authenticated — its old `GET_PUBLIC_PREFIXES` exception and the
`X-Checkout-Public` rate-limit special case were removed when this route replaced them.

Session (dashboard) surface — org-scoped JWT reads under `/api/v1/user/org/*`
(`app/api/user_org_payments_routes.py`; JWT-exempt from the API-key middleware via the
`/api/v1/user/` `EXEMPT_PATHS` entry — auth perimeter untouched):

| Route | Auth | Scoping | Rate limit |
|---|---|---|---|
| `GET /api/v1/user/org/payment-intents` | session JWT — `require_org_role("viewer")` | org_id server-derived from JWT → `_resolve_owner_address(org_id)` == `PaymentIntent.merchant_id`; **environment-scoped** (`Literal["test","live"]`, default `test`) IN the query; reuses the shared `intent_service.list_org_intents` (identical query to the API-key `GET /merchant/transactions` — no divergent second list); read-only; **404-free** but 409 `no_primary_wallet` when the org has no primary EVM wallet | 120/min **per IP** |

Browser/session counterpart of the API-key transactions list. The `/app` payments UI
(`/[locale]/app/payments`) reads it and is **hard-locked to `test`** — it sends no `environment`
param and shows no test/live toggle (mainnet routers are undeployed → `live` unpayable). Org
isolation (a session never sees another org's intents) is enforced in the SQL and pinned by
`tests/test_user_org_payments.py::test_cross_org_isolation_no_leak`.

Admin surface (server-to-server only; the web proxy denylists these paths):

| Surface | Auth | Notes |
|---|---|---|
| `GET /api/v1/audit/log`, `/admin/aml/*` (4 routes), `GET /health/config` | `X-Admin-Token` == **`ADMIN_API_TOKEN`** (dedicated env var) | Single `require_admin` dependency (`audit_routes.py`): constant-time `secrets.compare_digest`, denies everything when unset. **Never reuse `HMAC_SECRET` as an auth token** — startup fails in prod if the two are equal, too short, or placeholder. |

### Known follow-ups (tracked here so they're not forgotten — do not fix as a drive-by)

- **Redis-DOWN (degraded/fail-closed) path is untested** — with CI now running against a real
  Redis, no active test exercises health-`degraded` or rate-limit fail-closed with Redis
  absent (the in-memory-fallback test in `test_circuit_breaker.py` is skipped "pending
  rewrite"). Fail-closed is security-relevant; add coverage in a dedicated pass.
- **Error envelope inconsistency.** Middleware errors are flat `{error, message}` but route
  `HTTPException(detail={...})` responses get FastAPI-wrapped as `{detail: {...}}` — align in a
  dedicated docs/handler change.
- **Render provisioning before go-live:** Redis must be provisioned and `DEBUG=false` set —
  fail-closed rate limiting depends on both. Also set **`ADMIN_API_TOKEN`** (≥32 chars,
  distinct from `HMAC_SECRET`) — the admin surface is fully denied without it.
- **Phase C deferrals + a known-broken scope (2026-07-08).** Phase C shipped the session-authed
  org **payments read** view only (`GET /api/v1/user/org/payment-intents` +
  `/[locale]/app/payments`, session hook `useOrgPayments`). Narrowed out of C, still to build:
  the session `/api/v1/user/org/settlements` and `/api/v1/user/org/stats` endpoints and
  re-pointing the `/app` home stats widget off the wallet-sig `dashboard/stats`. **`dashboard_routes.py`
  scope is broken post-B**: it filters `PaymentSettlement.merchant == owner` (the org's *primary*
  wallet), so once an org's `settlement_wallet ≠ primary wallet` the home stats read **zero** — fix
  by scoping through the settlements→intents join (as the deferred `/stats` will); the widget is
  left untouched until then. **Pre-existing (plan anchor 10):** `/api/v1/merchant/profile` and
  `/api/v1/merchant/invoices` are `require_org_role`/JWT-authed but NOT in `EXEMPT_PATHS`, so
  they're unreachable in prod without `RSEND_DEV_AUTH_BYPASS` — new session routes correctly live
  under the exempt `/api/v1/user/org/` prefix instead.
- **Non-custodial `/app` residue after Phase A (2026-07-08).** Phase A removed the custodial
  dashboard surface (send/swap/flow, command-center, both `app/api/oracle/*` routes, the
  `forwarding/logs` transactions shell, the balances/clients/reports mocks, the `/app/settings`
  mock; sidebar/bottom-nav/topbar pruned and `settings` repointed to the live `/settings`).
  Still to clean in later passes (kept in A to stay subtractive/build-safe):
  (a) **custodial-tx-history plumbing** — `components/TransactionPersistence.tsx` (mounted in
  the `/app` layout) + `lib/tx-events.ts` + `components/auth/PostLoginMerge.tsx` +
  `hooks/useUserTransactions` persist send/swap tx history; now a dead listener (no emitters)
  but entangled with the auth/layout shell — remove once non-custodial payment-tracking is
  settled; (b) **root `app/page.tsx`** (non-locale `/`) is a legacy custodial consumer landing
  (`useSweepWebSocket`/`useSweepStats`, multi-chain Solana/Tron wiring) — out of the `/app`
  surface, needs its own decision; (c) **backend janitor leftovers** now caller-less from the
  web app — `EXEMPT_PATHS` entries `api/internal/signing` / `api/internal/oracle`,
  `/api/v1/forwarding` (sweeper), `/api/v1/distributions` (`app/security/api_keys.py`).

Closed (2026-07-05): **CI backend job now has a Redis service** (`redis:7`, health-checked,
`REDIS_URL=redis://localhost:6379/0` — plain scheme is CI/test-scoped, the `rediss://` guard
applies only when `is_prod`). `test_api.py::test_health` and
`test_circuit_breaker.py::…::test_health_all_healthy` go green in CI, unchanged (they keep
asserting `healthy`); CI matches the local baseline. Replaced in follow-ups by the
degraded-path coverage gap above.

Closed (2026-07-02): environment filter on intent reads/mutates (PR #2, migration 0005);
webhook `environment` dimension incl. outbound dispatch (migration 0006); fail-closed
`_get_merchant_id` (401, no shared bucket); **public checkout status view** — `/pay` now reads
`GET /api/v1/public/payment-intent/{id}` (id-as-secret, limited allowlist, per-IP rate limit,
verified working in production config without `RSEND_DEV_AUTH_BYPASS`). SQL-injection sweep
verdict: parametrized everywhere (ORM/bound params; only static `SELECT 1` probes and SQLite
PRAGMAs outside it).

Closed (2026-07-03, account-linking audit): **Google double-sign-up** — email-collision guard
added to the Google path (parity with GitHub), emails normalized on all ingest paths, the 409
now surfaces in the frontend (`OAuthConflictListener` → `AccountLinkingModal`) instead of
being swallowed, and `uq_users_email_lower` (migration 0007) backstops at the DB. Also fixed
en-route: OAuth signups never set the NOT NULL `account_type` (latent 500 for every fresh
Google/GitHub signup) — now `individual`. Still open (go-live checklist, provider consoles):
publish the Google OAuth consent screen; configure the prod GitHub OAuth app.

Closed (2026-07-03, user-auth audit remediation): **admin token separated from HMAC_SECRET**
(dedicated `ADMIN_API_TOKEN`, constant-time compare, fail-closed when unset — see admin table
above); **blocking logout** (`apps/web/lib/logoutClient.ts` gates client sign-out on the
backend session revocation — never a silent half-logout); **user PII cleared on sign-out**
(`rp_address_book`, `rsends.pendingMerge`, `rsend_antiphishing_code`, `rp_pending_queue`,
`rp_compliance_db` — cross-logout offline-first persistence consciously traded for
shared-device privacy).
