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

**Recipient gate (non-custodial invariant, Phase B; construction site moved in Phase D).** A
`PaymentIntent` **cannot** be created without a resolvable on-chain recipient — the single
construction site is now `intent_service.create_intent` (one `PaymentIntent(...)`,
`grep "PaymentIntent(" services/backend/app` = one hit), shared by BOTH the API-key create route
(`merchant_routes.create_payment_intent`, a thin wrapper passing `key_id` for monthly-limit +
usage-increment) and the session create route
(`user_org_payments_routes.create_org_payment_intent`, passing `org_id`). It calls
`resolve_recipient` first: per-intent override (Pydantic-validated) → else the org's
`settlement_wallet` (session path by `org_id`; API-key path by reverse lookup of the owner
wallet → its org). Fail-closed **422** when unresolvable
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

Session (dashboard) surface — org-scoped JWT routes under `/api/v1/user/org/*`
(`app/api/user_org_payments_routes.py` — read (C) + create/cancel (D);
`user_org_webhooks_routes.py`, `user_org_stats_routes.py` — Phase E; JWT-exempt from the API-key
middleware via the `/api/v1/user/` `EXEMPT_PATHS` entry — auth perimeter untouched). Every route
derives `owner = _resolve_owner_address(org_id)` (org_id server-derived from the JWT, never
client-supplied) and is environment-scoped (`Literal["test","live"]`, default `test`) IN the query.

**Owner-identity resolution (custodial-residue unblock, 2026-07-12).** The resolver lives in
`app/services/owner_identity.py` (re-exported from `merchant_profile_routes` under the old name;
16 call sites: payments/stats/webhooks/profile/invoice session routes). Precedence: (1) the org's
primary EVM wallet (SIWE-linked in `/settings/wallets`) — always wins, orgs with a linked wallet
resolve exactly as before; (2) fail-closed fallback to `organizations.settlement_wallet` — the
email-onboarded merchant path — ONLY if the address has no competing claim anywhere: any
`user_wallets` row (ANY org, **including unlinked/historical**), any other org's
`settlement_wallet`, or any `api_keys.owner_address` (active OR revoked) → 409
`settlement_wallet_conflict`, never a cross-tenant read (re-checked per request, so a later
SIWE link by the real owner immediately revokes a squatter's fallback). Neither wallet → 409
`no_primary_wallet` (kept for frontend compat). Accepted trade-off: linking a primary wallet
that differs from the settlement wallet flips the dashboard identity and settlement-keyed
intents drop out of view (still payable/settleable — checkout/indexer key by intent). Pinned by
`test_owner_identity_fallback.py`. The 409 `no_primary_wallet` notes in the table below predate
the fallback and now mean "neither primary wallet nor unclaimed settlement wallet". Exception:
`GET /user/org/stats` no longer 409s on `no_primary_wallet` — it computes the org-scoped
checklist booleans first and returns 200 with zeroed KPIs (the fresh-merchant onboarding state,
feeding the /app "Get started" card); `settlement_wallet_conflict` still propagates 409
(pinned by `test_org_stats_checklist.py`).

| Route | Required role | Scoping | Rate limit |
|---|---|---|---|
| `GET /api/v1/user/org/payment-intents` | `viewer` | `owner == PaymentIntent.merchant_id`; reuses shared `intent_service.list_org_intents` (identical query to API-key `GET /merchant/transactions` — no divergent list); read-only; 409 `no_primary_wallet` if none | 120/min **per IP** |
| `POST /api/v1/user/org/payment-intents` (create, D) | `operator` | goes through the SAME `intent_service.create_intent` as the API-key path (B's recipient gate via `org_id`; 422 unresolvable); `merchant_id == owner` so it lands in this org's read scope | 30/min **per IP** |
| `POST /api/v1/user/org/payment-intents/{id}/cancel` (D) | `operator` | scoped `(id, owner, env)` IN the query → **404** on miss/cross-tenant; pending-only → `cancelled` (400 else) | 30/min **per IP** |
| `GET /api/v1/user/org/webhooks` (Phase E) | `viewer` | `owner == MerchantWebhook.merchant_id` + env; response **never includes `secret`** (register-time one-shot only); read-only | 120/min **per IP** |
| `GET /api/v1/user/org/webhooks/{id}/deliveries` (Phase E) | `viewer` | webhook resolved with owner+env filter FIRST → **404** on empty (cross-tenant/cross-env/missing); paginated; **excludes `payload`/`response_body`** (OQ-E2, PII/secret avoidance) | 120/min **per IP** |
| `POST /api/v1/user/org/webhooks` (Phase E) | `operator` | register mirror — SAME `create_merchant_webhook` as the API-key path (SSRF egress guard + env stamp); returns `secret` **once**; 422 `WEBHOOK_URL_FORBIDDEN` on unsafe URL | 5/hour **per IP** |
| `POST /api/v1/user/org/webhooks/{id}/test` (Phase E) | `operator` | scoped `(id, owner, env)` → **404**/400; SAME `send_test_event` (egress-guarded) | 10/min **per IP** |
| `GET /api/v1/user/org/stats` (Phase E) | `viewer` | settlements attributed via the **intent join** (`settlement.intent_id → intent`, `intent.merchant_id == owner` + env) — NOT the broken primary-wallet filter; USD conversion via `price_service` + `app.tokens.registry`; read-only; carries the get-started checklist booleans (`settlement_wallet_set`/`has_api_key`/`has_paid_payment`, response `OrgDashboardStats(DashboardStats)` — the shared `DashboardStats` untouched); fresh-merchant safe: `no_primary_wallet` caught → **200 with zeroed KPIs + booleans**; `settlement_wallet_conflict` still 409 | 120/min **per IP** |

Browser/session counterpart of the API-key merchant API. The `/app` UI
(`/[locale]/app/{payments,webhooks,api-keys}` + the home stats widget) reads/writes here and is
**hard-locked to `test`** — it sends no `environment` param and shows no test/live toggle (mainnet
routers undeployed → `live` unpayable); the payments create form fixes chain = Base Sepolia (token
USDC/ETH). The webhook register/test session mirrors reuse the SAME service core as the API-key
routes (no divergent path). Org isolation is enforced in the SQL and pinned by
`test_user_org_payments.py::test_cross_org_isolation_no_leak` (read),
`test_user_org_intent_create.py::test_session_create_isolation` (create),
`test_webhook_reads.py::test_list_org_isolation` + `test_deliveries_cross_tenant_404` (webhooks),
and `test_org_stats_usd.py::test_stats_org_isolation_no_leak` (stats). The create/cancel and webhook
rate entries are inserted most-specific-first (each `/{id}/…` trailing-slash prefix precedes its
bare parent).

**Webhook test-fire SSRF guard (Phase E, shared path).** `send_test_event` and the real-delivery
`_attempt_delivery` (`webhook_service.py`) POST to a merchant-supplied URL. `check_webhook_egress`
now guards BOTH: reject non-HTTPS; reject literal/resolved loopback/private/link-local/reserved/
multicast/non-global IPs (v4, v6, IPv4-mapped v6); re-checked immediately before each POST
(DNS-rebinding window). A DNS-resolution *failure* is not treated as forbidden (unreachable host
can't hit anything internal; keeps reserved `*.example` test domains working) — and because
validation and the httpx connect share a resolver, a host that *can* reach a private IP is caught.
`create_merchant_webhook` rejects unsafe URLs at registration (422). This is the sanctioned touch
to the otherwise-frozen webhook pipeline; it also hardened the pre-existing API-key routes.

**`rsend_` vs `rsusr_` interop gap (OQ-E3 = A, product decision).** The `/app` API-keys tab
mounts the existing session `rsusr_` CRUD (`ApiKeysSettings`) + a documented link to
`/merchant/dashboard` for `rsend_` management. `rsusr_` user keys authenticate the session/dashboard
APIs but **cannot call the merchant payment API** (`verify_api_key` accepts only `rsend_`); minting
`rsend_` keys stays wallet-authenticated. The gap is surfaced in-UI (a note on `/app/api-keys`), not
hidden. Session-authed `rsend_` management (Option B) and accepting `rsusr_` on the merchant API
(Option C) were both rejected — they'd widen/rewire the auth perimeter.

Admin surface (server-to-server only; the web proxy denylists these paths):

| Surface | Auth | Notes |
|---|---|---|
| `GET /api/v1/audit/log`, `/admin/aml/*` (4 routes), `GET /health/config` | `X-Admin-Token` == **`ADMIN_API_TOKEN`** (dedicated env var) | Single `require_admin` dependency (`audit_routes.py`): constant-time `secrets.compare_digest`, denies everything when unset. **Never reuse `HMAC_SECRET` as an auth token** — startup fails in prod if the two are equal, too short, or placeholder. |

### Known follow-ups (tracked here so they're not forgotten — do not fix as a drive-by)

- **Re-key session tenancy on `org_id` (durable fix for the owner-identity fallback).** The
  wallet-address tenant key is custodial-era; the settlement-wallet fallback (2026-07-12) is a
  safe interim but leaves identity flips and a DoS-not-leak griefing vector (an org copying a
  wallet-less org's settlement address 409s both). Durable fix: nullable `org_id` on
  `payment_intents`/`merchant_webhooks` + backfill + re-scope the session queries (~16 sites);
  API-key visibility needs a union or org-bound keys. Est. 3-5 days, dedicated pass.
- **Retire the wallet-authenticated Merchant Dashboard (approved direction, 2026-07-12).**
  Supersedes OQ-E3's Option-B rejection: mint `rsend_` keys from `/app` with the session
  (org-scoped, admin role, `owner_address = resolve_owner_address(org)` — same identity chain),
  port list/revoke, then remove `/merchant/dashboard`, `/api/v1/keys/*` wallet-sig routes and
  `require_wallet_auth`. `/pay` and `verify_api_key` untouched. Sequenced after the fallback
  (shipped) — needs its own `ENDPOINT_LIMITS` entry and secret-shown-once UX.
- **Dormant custodial residue (audit 2026-07-12, batch as one subtractive pass):**
  `TransactionPersistence`/`ContactsPersistence`/`PostLoginMerge`/`lib/tx-events`/
  `useUserTransactions` (listeners without emitters, mounted in the `/app` layout) + the now
  caller-less `user_transactions`/`user_contacts`/`user_routes` APIs; `merchant_profiles`
  (wallet-keyed, superseded by `company_profiles` — migrate billing fields first);
  `blacklisted_wallets` (dead, superseded by `sanctions_list`); dead `EXEMPT_PATHS` entries;
  root non-locale `app/page.tsx` legacy landing (own decision). DB-only orphan tables
  (`anomaly_alerts`, `compliance_snapshots`) belong to the Alembic reconciliation (PR #18).
- **Redis-DOWN (degraded/fail-closed) path is untested** — with CI now running against a real
  Redis, no active test exercises health-`degraded` or rate-limit fail-closed with Redis
  absent (the in-memory-fallback test in `test_circuit_breaker.py` is skipped "pending
  rewrite"). Fail-closed is security-relevant; add coverage in a dedicated pass.
- **Error envelope inconsistency.** Middleware errors are flat `{error, message}` but route
  `HTTPException(detail={...})` responses get FastAPI-wrapped as `{detail: {...}}` — align in a
  dedicated docs/handler change.
- **Render provisioning before go-live:** Redis must be provisioned and `DEBUG=false` set —
  fail-closed rate limiting depends on both. Also set **`ADMIN_API_TOKEN`** (≥32 chars,
  distinct from `HMAC_SECRET`) — the admin surface is fully denied without it. Log hygiene
  (2026-07-13) also rides the posture: prod posture (`is_prod_posture`) drives root INFO +
  `httpx`/`httpcore`/`sqlalchemy.engine` at WARNING (`setup_logging(debug, prod_posture)`),
  so `DEBUG=false` (ideally plus `ENVIRONMENT=production`, which makes a future `DEBUG=true`
  flip refuse startup) is required for quiet prod logs; secret **redaction**
  (`SecretRedactionFilter`/`RedactingJsonFormatter` in `logging_config.py` — Alchemy-style
  URL-path keys, connection-string passwords, bearer tokens, `rsend_`/`rsusr_` keys) is
  active in every posture and pinned by `test_logging_redaction.py`/`test_logging_posture.py`.
- **Phase C deferrals — mostly closed by Phase E (2026-07-08).** Phase C shipped the session-authed
  org **payments read** view (`GET /api/v1/user/org/payment-intents` + `/[locale]/app/payments`,
  hook `useOrgPayments`). **Phase E built `GET /api/v1/user/org/stats`** (settlements→intents join
  by `settlement_wallet`, USD conversion via `price_service`/`app.tokens.registry`) **and
  re-pointed the `/app` home stats widget** off the wallet-sig `dashboard/stats` to it (hook
  `useOrgStats`). Legacy **`dashboard_routes.py` stays frozen and scope-broken** — it filters
  `PaymentSettlement.merchant == owner` (the org's *primary* wallet), reading **zero** once
  `settlement_wallet ≠ primary wallet`; the new `/stats` route (correct intent-join scope) is its
  replacement, `dashboard_routes.py` itself is intentionally left untouched. **Still deferred:** the
  session `/api/v1/user/org/settlements` endpoint. **Pre-existing (plan anchor 10):** `/api/v1/merchant/profile` and
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
