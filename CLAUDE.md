# RSends (non-custodial)

Monorepo for a non-custodial crypto payment platform:
- `apps/web` — Next.js frontend (checkout, dashboard, docs site)
- `services/backend` — Python FastAPI merchant API
- `packages/contracts` — Solidity contracts (Foundry): immutable fee router

## Integrator compatibility contract (read before changing a wire surface)

Third-party integrations run on servers we do not control, at whatever version the merchant
installed, for months — we cannot force an upgrade. The surfaces they depend on are
therefore **frozen**, and what exactly is frozen is written down in
**`docs/INTEGRATION_CONTRACT.md`** (normative copy, every promise anchored to `file:line`).

**Breaking a promise in that document is a review stop**, not a judgement call. Read it
before touching any of:

- `services/backend/app/services/webhook_service.py` — payload key set, signature scheme,
  header names, `X-RSend-Delivery-Id` format
- `services/backend/app/api/merchant_routes.py`, `app/services/intent_service.py`,
  `app/models/merchant_models.py` — request/response field names, `intent_id`/`reference_id`
  formats, enumerated values, error envelope shapes
- `services/backend/app/security/api_keys.py`, `app/middleware/api_auth.py` — key prefixes,
  the `Bearer` scheme, scope semantics
- `apps/web/app/pay/**` — the `/pay/{intent_id}` path shape and the 500 × 720 rendering floor
- the `headers()` block in `apps/web/next.config.mjs` — `frame-ancestors 'none'` and
  `X-Frame-Options: DENY` are promised permanently; the checkout must stay un-frameable

Adding a promise means adding or citing the test that holds it. Compatible additions (new
payload keys, new optional fields, **new enumerated values**) are always allowed — integrators
are contractually required to tolerate them.

Open work list: `contract-gaps-2026-08-12.md` (unenforced promises, ranked; plus known
inconsistencies). Its **item 1 is CLOSED (2026-09-04)** — the idempotency cache key was not
tenant-scoped, which was a live cross-merchant data-leak path and not just a missing test.
The key is now `(tenant, environment, path, idem_key)` (`app/middleware/idempotency.py:158`),
the body fingerprint sits **beside** the cached record (in the key it would make a
byte-different retry miss and create the duplicate the mechanism prevents; a mismatch is
`409 IDEMPOTENCY_KEY_REUSED`), and merchant paths fail **closed** on any Redis loss —
`FINANCIAL_PATH_PREFIXES`, matched with `startswith`, because `request.url.path` in a
middleware is the concrete path and an exact-match set could never cover
`/payment-intent/{id}/cancel`. Pinned by `tests/test_idempotency_tenant_scope.py`.
Two residues, deliberate: the tenant is the owner **wallet address** (it tracks
`PaymentIntent.merchant_id`, so it moves with the org_id re-key below, not before it), and
the session surface's `environment` is a query param that is in neither the path nor the
fingerprint — unreachable while `/app` is test-locked and sends no idempotency key.

## Build invariants (apps/web)

- **`"skipLibCheck": true` in `apps/web/tsconfig.json:11` is load-bearing — do not remove it.**
  It reads like a default someone left on; it is not. The TRON wallet adapters do not typecheck
  without it, and every resulting error is a third-party declaration defect that no change to our
  code can fix. The load-bearing one:
  `Cannot find module 'tronweb/lib/esm/types/Transaction'` — `@tronweb3/tronwallet-abstract-adapter`
  re-exports its `Transaction` / `SignedTransaction` types from a **deep path that is not in
  tronweb's `exports` map**, so the module resolver cannot follow it. That re-export is also
  precisely what makes one shared build/sign/broadcast path possible
  (`apps/web/lib/web3/tron/tronTransfer.ts`), so it cannot be worked around by importing
  differently. The other five are two broken `@walletconnect/modal` type paths and three
  `Type 'Uint8Array' is not generic` errors inside tronweb's own `.d.ts`. Removing the flag breaks
  `next build`.
- **No TronGrid API key in the browser.** The checkout's TronWeb instance
  (`apps/web/lib/web3/tron/tronClient.ts`) calls TronGrid keyless, deliberately. A key in a
  `NEXT_PUBLIC_*` variable is not a secret — it ships to every payer. If keyless rate limits ever
  bite on mainnet, the answer is a backend proxy as its own task, never a key in the bundle.

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
- **A supported chain must sit in exactly one environment set.** The chain↔key gate in
  `intent_service.create_intent` is an allowlist-of-the-OPPOSITE (`test` refuses
  `_MAINNET_CHAINS`, `live` refuses `_TESTNET_CHAINS`), so a chain in **neither** set is
  refused by neither branch and is creatable on test AND live keys. Adding a chain to
  `app/token_registry.json` is what arms this: `chain_is_supported` starts returning True.
  Registry entry and set membership therefore land in the SAME change; pinned for every
  registry chain by `test_tron_nile.py::test_every_supported_chain_is_in_exactly_one_environment_set`.
  Testnet-ness for a **watch-only** chain (no EVM chain id) is carried by NAME in
  `chain_access.WATCH_ONLY_TESTNET_CHAINS` — `tron_nile` today. It must never be carried by
  putting a TRON chain id in `TESTNET_CHAIN_IDS`: that table is read by the EVM boot guard,
  which would `eth_chainId` a TRON node and `SystemExit` the backend. `is_testnet_chain`
  (id-keyed) and `is_watch_only_testnet` (name-keyed) are both fail-closed to mainnet.
  Two TRON networks are live in code: `tron` (mainnet, `live`, chain id 728126428) and
  `tron_nile` (testnet, `test`, chain id 3448148188), each with its own pinned genesis
  (`tron_chain_identity.TRON_GENESIS_BLOCK_IDS`), its own node-URL env var, and its own
  cursor row. `indexer_cursors.chain_id` and `payment_settlements.chain_id` are `BIGINT`
  since migration 0020 — Nile's id does not fit a Postgres `INTEGER`, and SQLite (which CI
  runs on) cannot reproduce that failure.
- **Webhook trust.** Outbound webhooks are signed HMAC-SHA256 over `"{timestamp}.{body}"` with a
  per-merchant secret, headers `X-RSend-Signature` / `X-RSend-Timestamp`, 5-minute freshness
  window (`services/backend/app/services/webhook_service.py`). Consumers must verify before
  trusting. This is the **only** signing scheme — do not introduce another.
- **Fail closed.** Auth/isolation fallbacks must deny (401/404), never fall into a shared or
  default bucket. `_get_merchant_id` raises 401 when there is no authenticated client; **no
  merchant route is public**. The only sanctioned unauthenticated read is the dedicated
  payer-facing view in `app/api/public_routes.py` (see below).
- **One account per email (user auth).** Social login (Google/GitHub) was removed from the
  product (2026-07-13) — email/password is the only signup/login path (SIWE links wallets to
  an existing session, it is not a signup). Emails are normalized (`lower().strip()`) on the
  ingest schemas and again in the login handler; signup on an existing email gets **409
  `email_already_exists`** (block-and-guide via `AccountLinkingModal` → login). DB backstop:
  unique index `uq_users_email_lower` on `lower(email)` (User `__table_args__` + migration
  0007 — which reports-and-stops on pre-existing duplicates, never auto-merges). The orphan
  `users.google_sub`/`github_sub`/`github_username` columns stay in place untouched (no
  migration; DB reconciliation is a separate task).
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
`PaymentIntent` **cannot** be created without a resolvable on-chain recipient — the invariant is
**exactly one persisted construction site**: `intent_service.create_intent` (the only place a
`PaymentIntent(...)` reaches `db.add`). Known, named exception:
`webhook_service._build_test_event_payload` constructs a **synthetic, never-persisted** intent
(the function has no `db` handle; the object only feeds `_build_payload("test", …)` so the
"Send test" event ships the exact production shape — PR #48). It cannot bypass the gate because
it never touches the DB. Mechanical check:
`grep -rn "PaymentIntent(" services/backend/app | grep -v "class PaymentIntent"` = exactly these
**two** hits (the persisted site + the synthetic one). Any third hit is a **review stop**: either
it is a recipient-gate bypass, or it must be added here as a named, justified exception in the
same review. `create_intent` is shared by BOTH the API-key create route
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
**other org's** `user_wallets` row (**including unlinked/historical**), any other org's
`settlement_wallet`, or any `api_keys.owner_address` (active OR revoked) → 409
`settlement_wallet_conflict`, never a cross-tenant read (re-checked per request, so a later
SIWE link by the real owner immediately revokes a squatter's fallback). All three checks carve
out the **resolving org itself and nothing more** — the two over a nullable tenant column
(`user_wallets.org_id`, `api_keys.org_id`) with a NULL arm, since a bare `!= org_id` would not
count a NULL-org row. The foreign-org promise is unchanged, unlinked rows included; only
self-claims stopped counting (fixed 2026-08-18 — an org whose `settlement_wallet` was an
address it had SIWE-linked and later unlinked 409'd against itself permanently, locking its
own dashboard/stats/keys with no in-product remedy; the `user_wallets` check was the one of
the three that lacked the carve-out). Neither wallet → 409
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
| `POST /api/v1/user/org/merchant-keys` (Option B, 2026-07-15) | `admin` | mints a REAL `rsend_test_` merchant key from the session — SAME `generate_api_key` + `api_keys` table as the wallet route; `owner_address = resolve_owner_address(org)`; scope pinned `write`, env pinned `test`; row stamped `org_id` (0011; NOT NULL + tenant key since 0014) so the owner-identity conflict check excludes the org's OWN keys (self-conflict trap); 5-active cap per (org, env) → 409 `max_keys_reached`; resolver 409s propagate; plaintext returned **once** | 5/hour **per IP** |
| `GET /api/v1/user/org/merchant-keys` | `viewer` | prefix-only list, `org_id == org` ONLY (0014 re-keyed key tenancy on org_id and backfilled historical wallet-minted keys to their org; a foreign org's key stays invisible even on a shared owner address); never key material | 120/min **per IP** |
| `POST /api/v1/user/org/merchant-keys/{id}/revoke` | `admin` | soft-revoke, idempotent; tenant scope `(id, org_id)` IN the query → **404** on miss/cross-tenant; no owner-identity resolution needed | 10/min **per IP** |
| `GET /api/v1/user/org/stats` (Phase E) | `viewer` | settlements attributed via the **intent join** (`settlement.intent_id → intent`, `intent.merchant_id == owner` + env) — NOT the broken primary-wallet filter; USD valuation via the **static peg** on `app.tokens.registry` (`get_usd_peg`; no price feed — `price_service` was deleted). A token with **no peg is EXCLUDED from the aggregate and reported**, never summed as zero: `volume_24h_unpriced_count`/`_symbols` on `OrgDashboardStats`, so a merchant paid in ETH is distinguishable from a merchant paid nothing; read-only; carries the get-started checklist booleans (`settlement_wallet_set`/`has_api_key`/`has_paid_payment`, response `OrgDashboardStats(DashboardStats)` — the shared `DashboardStats` gained only the defaulted `RecentTransaction.amount_usd_known`, so frozen `dashboard_routes.py` is untouched); fresh-merchant safe: `no_primary_wallet` caught → **200 with zeroed KPIs + booleans**; `settlement_wallet_conflict` still 409 | 120/min **per IP** |

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

**`rsend_` vs `rsusr_` — Option B implemented (2026-07-15, supersedes OQ-E3 = A).** The `/app`
API-keys tab now has TWO honest sections: session-minted **merchant keys** (`MerchantApiKeys` →
`/api/v1/user/org/merchant-keys`, table above — the real payment-API keys, env-pinned `test`)
and the pre-existing `rsusr_` **dashboard keys** (`ApiKeysSettings`, unchanged; note that
`rsusr_` verification — `require_api_key_scope` — is still wired to zero routes, so those keys
currently authenticate nothing; binding or retiring them is an open decision). The old interop
banner and the `/merchant/dashboard` hand-off link were removed (that dashboard never minted
keys — it only consumed a pasted one). `verify_api_key` still accepts only `rsend_`; accepting
`rsusr_` on the merchant API (OQ-E3 Option C) stays rejected. The wallet-signed `/api/v1/keys/*`
routes remain until the Merchant Dashboard retirement (follow-up below).

Admin surface (server-to-server only; the web proxy denylists these paths):

| Surface | Auth | Notes |
|---|---|---|
| `GET /api/v1/audit/log`, `/admin/aml/*` (4 routes), `/admin/approvals` (list) + `/{org_id}/approve\|decline`, `GET /health/config` | `X-Admin-Token` == **`ADMIN_API_TOKEN`** (dedicated env var) | Single `require_admin` dependency (`audit_routes.py`): constant-time `secrets.compare_digest`, denies everything when unset. **Never reuse `HMAC_SECRET` as an auth token** — startup fails in prod if the two are equal, too short, or placeholder. X-Admin-Token surfaces must also be exempt from the API-key middleware (`EXEMPT_PATHS`) or they 401 in prod before `require_admin` runs — pinned by `test_admin_approvals.py::test_admin_approvals_exempt_from_api_key_middleware`. |

### Known follow-ups (tracked here so they're not forgotten — do not fix as a drive-by)

- **Re-key session tenancy on `org_id` (durable fix for the owner-identity fallback).** The
  wallet-address tenant key is custodial-era; the settlement-wallet fallback (2026-07-12) is a
  safe interim but leaves identity flips and a DoS-not-leak griefing vector (an org copying a
  wallet-less org's settlement address 409s both). **api_keys slice DONE (0014, 2026-07-18):**
  every key row carries a NOT NULL `org_id` (backfilled report-and-stop), key mint/list/revoke/
  cap are org-scoped, and both mint routes stamp org fail-closed — keys are org-bound.
  REMAINING: nullable `org_id` on `payment_intents`/`merchant_webhooks` + backfill + re-scope
  the session queries (~16 sites); `client_id`/`merchant_id` stamping is still the wallet
  address. Est. 3-5 days, dedicated pass.
- **Retire the wallet-authenticated Merchant Dashboard (approved 2026-07-12; WEB SURFACE
  REMOVED 2026-07-16).** Session minting + list/revoke are live
  (`/api/v1/user/org/merchant-keys`, admin role, `resolve_owner_address` identity chain, own
  `ENDPOINT_LIMITS` entries, secret-shown-once UX) — shipped 2026-07-15. The `/merchant/dashboard`
  page (pasted-key UI, never SIWE) is gone: page archived to `apps/web/_archive/merchant-dashboard.tsx`
  (kept for its chain-picker / multi-token / metadata create-modal code, wanted for /app at
  mainnet), its `/api/merchant/[...path]` proxy deleted, `/merchant/:path*` now 307s to `/en/app`
  via `next.config.mjs` redirects (which run before middleware; the `merchant` matcher exclusion
  was dropped). Lock-out verified on prod before removal: zero passwordless users, one api_key
  (operator's own test key). REMAINING (post-Manimama, with the org_id re-key): the
  `/api/v1/keys/*` wallet-sig routes, frozen `dashboard_routes.py` (zero web callers),
  `wallet_session_routes.py`, the `/api/v1/keys` `EXEMPT_PATHS` entry + `ADMIN_PATHS` middleware
  branch; `require_wallet_auth` itself stays until the dormant custodial surfaces
  (splits/forwarding/distributions) also go. `/pay` and `verify_api_key` untouched. Also decide
  `rsusr_`'s fate (verification wired to zero routes). Note: 0011 (`api_keys.org_id` + resolver
  own-org carve-out) and 0014 (backfill + NOT NULL + org-scoped key tenancy; the wallet-signed
  `POST /api/v1/keys/generate` now resolves the signer's org via `resolve_org_for_wallet` and
  422s fail-closed instead of minting a NULL-org key) are the completed api_keys slices of the
  org_id re-key follow-up above.
  Capability gap accepted at removal: /app is test-env-locked, so until it grows an environment
  toggle there is no UI over live/mainnet data (live routers undeployed, so nothing is usable
  there yet anyway).
- **Dormant custodial residue (audit 2026-07-12, batch as one subtractive pass):**
  ~~`TransactionPersistence`/`ContactsPersistence`/`PostLoginMerge`/`lib/tx-events`/
  `useUserTransactions`~~ — frontend cluster ARCHIVED 2026-07-18 to
  `apps/web/_archive/custodial-persistence/` (console-404 cleanup pass; the listeners had
  no emitters and the fetched data no readers). The backend `user_transactions`/
  `user_contacts`/`user_routes` routers are STILL REGISTERED in main.py (they were never
  removed — 401/200, not 404) and are now truly caller-less (`useUserRoutes.ts` also
  caller-less, left in place): remove them in this batch pass; `merchant_profiles`
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
- **Asset identity is still inferred, not recorded (chain-identity branch, 2026-09-02).** The
  chain half is fixed — a settlement row now serialises a machine-stable `chain_key` assembled in
  `app/services/chain_display.py`, and no display surface guesses a chain. The TOKEN half is not,
  and these are the pieces left, deliberately deferred rather than forgotten:
  - **The display path cannot identify a TRON token.** `app/tokens/registry.py` registers chain
    ids 8453/84532/1/42161 only, so `_token_info(3448148188, "TXYZ…")` misses and the row reports
    `currency="TOKEN"` with the *pricing* copy "not valued" — an IDENTIFICATION failure wearing a
    VALUATION failure's words. `_usd_value` short-circuits before `get_usd_peg` ever runs. The
    agreed fix is an ADDITIVE adapter (money registry first — it already knows both TRON USDT
    contracts with decimals 6 — display registry second, supplying `peg_usd` plus the Arbitrum,
    WETH and cbBTC identities the money registry has never held). A straight swap would regress
    those six token/chain combinations from "identified, unpriced" to "unidentified". Own branch,
    not a drive-by; it also owes an invariant test that the two registries never disagree on
    decimals for a token both know.
  - **Neither poller records what the chain told it.** `tron_poller.py` reads TronGrid's
    `token_info` in exactly two places and takes only `address` from it — `symbol`, `decimals`
    and `name` are dropped at the boundary and survive nowhere: no column, no JSON blob, no log
    line. `payment_indexer.py:765` does the identical thing on the EVM side. So token identity is
    always RE-DERIVED from a policy table rather than recorded from observation, and a token no
    registry knows can never be named. Fixing it needs a migration, which Emilio writes.
- **`admin/transactions/page.tsx:52` sends unknown networks to Etherscan.** A ternary whose `else`
  branch is `https://etherscan.io`, so a TRON tx hash links to an Ethereum explorer. Admin-only,
  so it is not a merchant-facing lie, but it is the same class of defect the merchant surfaces
  just had removed — `lib/web3/explorer.ts` is name-keyed with no fallback and returns null on a
  miss, which is the shape to copy. Its own change.
- **`.claude/settings.json` allowlists `-p no:logging`, which `conftest.py:16-23` forbids.** Six
  pre-approved Bash entries (`:277,278,279,282,283,339`) carry the flag that kills `caplog` and
  fabricates phantom ERRORs in the depth-finality/indexer-cursor/reorg-evidence modules. They also
  reference `./venv/bin/python`, a path the Makefile no longer creates (it builds
  `services/backend/.venv`). Stale on both counts.
- **A from-scratch `alembic upgrade head` on SQLite dies at 0007.** It runs an unguarded
  `CREATE UNIQUE INDEX uq_users_email_lower`, which migration 0001's `Base.metadata.create_all`
  has already built from the `User` model → `index uq_users_email_lower already exists`. 0007
  lacks the `_has_index` guard that 0011/0017/0024 carry for exactly this reason. Found
  2026-09-04 while verifying 0024, **pre-existing and deliberately left alone**: editing a
  revision that has already run in production is its own decision, and the blast radius is
  limited — Postgres deployments are long past 0007, and the tests build their schema with
  `create_all`, never with alembic. What it costs is the ability to verify a *later* revision
  end-to-end on SQLite. The workaround, if you need that: `create_all` → `alembic stamp head` →
  `downgrade -1` → `upgrade head`, which exercises just the revision under test.
  Two invocation gotchas that cost time when you do: run alembic as
  `venv/bin/python venv/bin/alembic …`, because the project's local `alembic/` package shadows
  the installed library from `services/backend` (this is why every revision imports `op` lazily
  inside `upgrade()`), and `venv/bin/alembic` on its own has a stale shebang pointing at a
  `~/Desktop/...` path that no longer exists.
- **`docs/INTEGRATION_CONTRACT.md:667-669` quotes 8 keys for the public checkout view; the code
  has 12.** `public_routes.py:40-79` and its pinned test `test_public_intent_view.py:40-46` were
  extended and the document was not. Code is the source of truth, so this is a doc fix.
- **The `dashboard_routes` retirement batch is gated on "post-Manimama", an engagement that ended
  in July 2026.** The gate as written can never fire, so the batch cannot be scheduled. It should
  be re-gated on the `org_id` re-key alone, which is the real technical precondition — but that is
  a scheduling decision, so the rewording is left to Emilio rather than done in passing. Note also
  that the route is NOT dead in the meantime: it is mounted (`main.py:386`), its prefix is in
  `GET_PUBLIC_PREFIXES` so a GET bypasses the API-key middleware and reaches
  `@require_wallet_auth`, and it is absent from the web proxy's deny-list. It has no known caller,
  which is not the same thing.
- **Render provisioning before go-live:** Redis must be provisioned and `DEBUG=false` set —
  fail-closed rate limiting depends on both. Also set **`ADMIN_API_TOKEN`** (≥32 chars,
  distinct from `HMAC_SECRET`) — the admin surface is fully denied without it. Log hygiene
  (2026-07-13) also rides the posture: prod posture (`is_prod_posture`) drives root INFO +
  `httpx`/`httpcore`/`sqlalchemy.engine` at WARNING (`setup_logging(debug, prod_posture)`),
  so `DEBUG=false` (ideally plus `ENVIRONMENT=production`, which makes a future `DEBUG=true`
  flip refuse startup) is required for quiet prod logs; secret **redaction**
  (`SecretRedactionFilter`/`RedactingJsonFormatter` in `logging_config.py` — Alchemy-style
  URL-path keys, Telegram bot tokens in the URL path (`api.telegram.org/bot<token>/…`),
  connection-string passwords, bearer tokens, `rsend_`/`rsusr_` keys) is
  active in every posture and pinned by `test_logging_redaction.py`/`test_logging_posture.py`.
- **Phase C deferrals — mostly closed by Phase E (2026-07-08).** Phase C shipped the session-authed
  org **payments read** view (`GET /api/v1/user/org/payment-intents` + `/[locale]/app/payments`,
  hook `useOrgPayments`). **Phase E built `GET /api/v1/user/org/stats`** (settlements→intents join
  by `settlement_wallet`, USD valuation via the static peg on `app.tokens.registry`) **and
  re-pointed the `/app` home stats widget** off the wallet-sig `dashboard/stats` to it (hook
  `useOrgStats`). Legacy **`dashboard_routes.py` stays frozen and scope-broken** — it filters
  `PaymentSettlement.merchant == owner` (the org's *primary* wallet), reading **zero** once
  `settlement_wallet ≠ primary wallet`; the new `/stats` route (correct intent-join scope) is its
  replacement, `dashboard_routes.py` itself is intentionally left untouched — with one named
  exception (2026-08-30): its `RecentTransaction.recipient` line stopped lowercasing the settlement
  merchant, because `.lower()` destroys a base58check address rather than merely changing it. Both
  stats routes now share `display_payment_address` (`app/security/input_validator.py`). The fix is
  **latent** there: that route's scope filter is `PaymentSettlement.merchant == wallet_address.lower()`,
  which matches zero base58 merchants, so no TRON row ever reaches the line. It was changed to stop
  the two routes diverging, not because it is reachable; the scope filter stays as-is. **Still deferred:** the
  session `/api/v1/user/org/settlements` endpoint. **Pre-existing (plan anchor 10):** `/api/v1/merchant/profile` and
  `/api/v1/merchant/invoices` are `require_org_role`/JWT-authed but NOT in `EXEMPT_PATHS`, so
  they're unreachable in prod without `RSEND_DEV_AUTH_BYPASS` — new session routes correctly live
  under the exempt `/api/v1/user/org/` prefix instead.
- **Non-custodial `/app` residue after Phase A (2026-07-08).** Phase A removed the custodial
  dashboard surface (send/swap/flow, command-center, both `app/api/oracle/*` routes, the
  `forwarding/logs` transactions shell, the balances/clients/reports mocks, the `/app/settings`
  mock; sidebar/bottom-nav/topbar pruned and `settings` repointed to the live `/settings`).
  Still to clean in later passes (kept in A to stay subtractive/build-safe):
  (a) **custodial-tx-history plumbing** — DONE 2026-07-18: the persistence cluster
  (`TransactionPersistence`/`ContactsPersistence`/`PostLoginMerge`/`tx-events`/
  `useUserTransactions`/`useUserContacts`) was unmounted from the `/app` layout and archived
  to `apps/web/_archive/custodial-persistence/`; (b) **root `app/page.tsx`** (non-locale `/`) is a legacy custodial consumer landing
  (`useSweepWebSocket`/`useSweepStats`, multi-chain Solana/Tron wiring) — out of the `/app`
  surface, needs its own decision; (c) **backend janitor leftovers** now caller-less from the
  web app — `EXEMPT_PATHS` entries `api/internal/signing` / `api/internal/oracle`,
  `/api/v1/forwarding` (sweeper), `/api/v1/distributions` (`app/security/api_keys.py`).
- **`feeUnavailable` is sent by the backend and dropped by the frontend.**
  `build_onchain_payment` (`router_registry.py`) sets it when the live `quoteFee` fails, and
  `RawPaymentIntent` declares it (`apps/web/lib/web3/paymentIntent.ts`), but `normalizeIntent`
  never copies it into `OnChainIntent` — it has always been discarded. Nothing needs it today:
  the checkout infers the degraded case from `fee == null` and the *unavailable* case is now a
  separate state (`chain_unreachable`), so wiring it would add an unread field. It is listed
  here because it is a wire field the backend maintains and the client throws away, and the
  next person to look for it will assume it works. Either carry it into `OnChainIntent` with a
  consumer, or stop sending it.
- **The post-payment sync poll fails silently forever.** `usePaymentIntent` in `sync` mode
  (started when the payer's tx mines) keeps its cadence through every error and never
  surfaces one. The copy stays true — the payment IS confirmed on-chain and the explorer link
  is on screen — but this is the last place in `/pay` where a backend outage is not announced:
  the payer sees "Updating the merchant's records" for as long as it lasts. The `initial`
  phase got a give-up window + `unreachable` card (2026-08-23); `sync` deliberately did not,
  because there the money has already moved and stopping the poll helps nobody. Decide what a
  stalled sync should SAY, then implement it — it is a copy/threshold decision, not a bug.
- **`/pay` is not runnable locally without `NEXT_PUBLIC_WC_PROJECT_ID`.** The var is in
  `apps/web/.env.example` (empty) but is not optional: RainbowKit throws
  `No projectId found` at module load, so `/pay` renders the error boundary instead of the
  checkout and no amount of stubbing gets past it. Any non-empty string works for local work
  (WalletConnect itself stays unusable). See the note added to `.env.example`.
- **The amount-scale gate cannot protect 18-decimal tokens — only `Numeric` can.**
  `create_intent` rejects `400 AMOUNT_PRECISION_EXCEEDED` when an amount's decimal scale exceeds
  the token's `decimals`, so `to_base_units` never silently rounds a stored amount. That gate is
  exact for 6-decimal tokens (USDC/USDT/EURC): `amount * 10^6` stays inside float64's exact
  integer range up to ~9.0e9 tokens, far beyond any invoice. It is **structurally unable** to do
  the same for the 18-decimal ones (ETH/DAI, enabled on base/base_sepolia/ethereum today).
  `PaymentIntent.amount` is a `Float`, and FastAPI parses the body with `json.loads`, so a JSON
  number is already a rounded float64 **before any validator runs** — `mode="before"` included.
  A client sending `10.000000000000000001` ETH has had the excess destroyed upstream; the gate
  sees scale 1 and correctly accepts what is now `10.0`. Sending the amount as a JSON string does
  not help: Pydantic coerces it to the same float. float64 holds `amount * 10^18` exactly only up
  to ~0.009 tokens, so above that the scale is unknowable in principle, not merely unchecked.
  **The fix is the `Float` → `Numeric(78, 0)` (or scaled-decimal) migration on `payment_intents`,
  not a better validator** — `settlement_models.py:72-73` already uses `Numeric`, commented
  "never float", so the settlement side is right and the intent side is the outlier. Until then,
  treat the amount gate as airtight for stablecoins and best-effort for native/18-decimal assets.
- **An unenrichable TRON transaction freezes the poller's cursor indefinitely, and pages
  nobody.** `tron_poller` fails closed by design: a transfer whose `/v1/transactions/{txid}/events`
  enrichment errors, matches nothing, or matches ambiguously writes no settlement row, and the
  cursor pins to that transaction's `block_timestamp` (`min_timestamp` is inclusive, so it is
  re-observed, never skipped). That is the correct trade — a payment re-observed forever is
  recoverable, one skipped once is not — but the consequence is that the tick retries the same
  transaction every 60s with an `ERROR`, and **while the cursor is frozen no LATER TRON payment
  is recorded either**, so a single poison transaction silently stalls the whole chain's
  observation behind a log line no one is watching. There is no alert-service hook: unlike the
  EVM indexer, which escalates to a single `logger.critical` + `INDEXER_STALLED` alert + gauge
  at `STALL_TICKS` consecutive failures (`payment_indexer._note_failure`), the TRON poller has
  no equivalent. The fix is that hook, in the `INDEXER_STALLED` style, keyed on consecutive
  ticks blocked at the same cursor. Deferred to slice 3 or later — do not build it as a
  drive-by. Unchanged by the Nile addition, which gave each network its own cursor row: the
  stall is now per network (a poisoned Nile transaction does not stall mainnet, and vice
  versa) but is still unalerted on both, and the hook must be keyed per network when built. (Slice 3 did build the **webhook** redrive this note's sibling gap needed —
  `tron_matcher.redrive_tron_webhooks` — because the EVM unfired-webhook sweep is
  `chain_id`-scoped inside an EVM-only watcher and would never have retried a TRON dispatch.
  The cursor-stall alert is still open.)
- **A TRON intent that expires between payment and matching is never matched, silently.** The
  TRON matcher (`app/services/tron_matcher.py`) requires `status == pending`, so an intent the
  expiry loop flips to `expired` in the ≤60s window between the payer's transfer and the next
  poller tick gets **zero candidates forever**: the settlement row stays `pending` with
  `intent_id` NULL, the merchant has the money, and nothing in the product says so. This is a
  deliberate **divergence from the EVM path**, which treats `expired` as payable
  (`payment_indexer.py:826-832`, "money on-chain wins over the timer — rescue the intent
  instead of stranding a settled payment"). The reason the EVM race is benign and this one is
  not: the settlement hold that normally protects a paid-but-unfinalized intent from the expiry
  sweep (`intent_service.settlement_hold_exists`) correlates on `intent_id`, which is NULL on a
  TRON settlement until the matcher runs — so on TRON the hold cannot engage before the race is
  already lost. Pinned as intentional by
  `test_tron_matching.py::test_an_intent_that_expired_since_payment_is_not_matched`. Fixing it
  means either adding `expired` to the matcher's candidate statuses (EVM parity) or holding on
  `(chain, recipient, window)` before an `intent_id` exists — a decision, not a bug fix.
- **The tx-hint pipeline narrowed that gap without closing it, and the remainder is now the
  worst-shaped half.** The hint (`tron_verifier` / `tron_hints`, `tron_payment_hints`) means a
  transfer whose intent expires between broadcast and solidification **does** get its
  `PaymentSettlement` row recorded, from the hash the payer's browser submitted, without waiting
  for the address scan. So the money is no longer invisible. But `tron_matcher` still requires
  `status == pending`, so the intent is still never closed: **the settlement exists, the merchant
  holds the funds, and no `payment.completed` webhook ever fires.** That is arguably worse than
  before to operate, because the row now sits in the database looking settled while the merchant's
  own systems were never told — a silent discrepancy rather than a silent absence.
  The EVM path already models exactly this situation and has for a long time:
  `late_payment_policy` (`auto_complete` | `reject` | `review`), `completed_late` and
  `late_minutes` on `PaymentIntent`, with the handling in `webhook_service._handle_late_payment`.
  TRON reads none of it. The shape of the fix is therefore probably not new machinery but
  teaching the TRON matcher the late-payment vocabulary the EVM side already speaks, together
  with whichever of the two options in the note above is chosen. **Own branch, after the TRON
  checkout branch merges** — it changes when a merchant gets paid, which is not a drive-by.
- **Review at mainnet launch: surfaces that name a token/chain pair (2026-09-02).** The
  landing "how it works" card and the pricing FAQ were corrected — they claimed
  `USDT on Base`, which is `enabled: false` (`bridged_asset`) in `token_registry.json` and
  400s at `intent_service.py:439` regardless of environment or activation, so it never
  becomes true. The root `<meta description>`/`keywords` (`apps/web/app/layout.tsx`) dropped
  chain names entirely, deliberately: it ships on every page and is the first string to go
  stale. **These remain, all asserting pairs that are gated rather than false, and all need a
  read the day mainnet opens:** `README.md:177-181` (a `## Networks` table listing Base and
  Ethereum mainnet as `live`, contradicting `docs/INTEGRATION_CONTRACT.md:43`);
  `merchant_models.py:341` (OpenAPI description offering `ARBITRUM`, which is in no registry);
  `docs/INTEGRATION_CONTRACT.md:267` (currency enum includes `cbBTC` and `DEGEN`, neither
  chargeable); `features.savedRoutes.howItWorks[1].body` and `.example.text` (USDC×Arbitrum as
  a present-tense flow, five locales); `twoPaths.businesses.b4` (bare `"USDC · USDT"`);
  `how-it-works/page.tsx:28` (`method: 'USDC · Base'`, hardcoded, no testnet marker at the
  render site); `CompanyProfileForm.tsx:42` (onboarding offers USDT and EURC as primary
  stablecoin); and this file's own former claim that DAI is enabled on
  `base`/`base_sepolia`/`ethereum` — only `ethereum` is true (`base` is `enabled: false`
  `low_demand`, `base_sepolia` has no DAI at all). **The two ToS keys
  (`legal.terms.sections.service.body`, `.settlement.body`) still carry the uncorrected
  claim in five locales** and are Emilio's to write — that is a live gate, not a launch
  review. Note also that **no in-app path ever sets `activation_status = "active"`**
  (`org_service.py:122,162` write `"not_started"`), so every mainnet intent 403s today: that
  is what makes the gated pairs false in practice and not only in principle.
- **`apps/web/messages/{es,fr,de}.json` are partly untranslated English.** The whole
  `auth.whySignIn.*` block (es/fr/de:139-159) plus `hero.titleLine1/2/3`,
  `hero.ctaPrimary/ctaSecondary` and `hero.metrics.*` ship the English strings verbatim in
  three locales. `localeKeys.test.ts` checks key shape and emptiness, not that a value
  differs from `en`, so nothing catches it. Larger than any one change and Emilio's call how
  to handle it; the 2026-09-02 copy fix deliberately left those three at English rather than
  creating half-translated blocks.
- **EURC's absence from the checkout has the wrong reason recorded.**
  `deviceShowcase.test.tsx:11` and `showcaseFixture.ts:14` say EURC "is in NO backend registry
  and create-intent 422s it". False: `token_registry.json` carries EURC `enabled: true` on
  both `ethereum` and `base`, so `token_is_enabled("base","EURC")` is `True`. The correct
  reason is **"not offered on the deployed Base Sepolia router"** — the `enabled: false` lives
  in the web registry (`payTokens.ts:56`, pinned by `payTokens.test.ts:27-32`). The tests pass
  either way; only the justification is wrong, which is worse than no comment because it stops
  the next person checking. Belongs with issue #87 (the two token gates diverging).
- **Mobile CLS on the landing hero: ~0.48 at 390, measured, and it is the hero.** Seven cold
  loads of `/it` at 390×844 give 0.4799–0.4943, spread ±0.014, essentially unchanged by the
  2026-09-02 mockup spacing work (0.4948 → 0.4828 mean, i.e. inside the noise). Warm dev
  servers report ~0.003 for the same page and that number is not representative — measure on a
  cold build. Consequence for the record: the 0.0020 → 0.0031 delta attributed to `7fe3d1f3`
  in its own commit message was **noise, not signal from either the `100dvh` removal or the
  44→40px caption gap**; there is nothing to attribute. Anyone fixing the hero should treat
  0.48 ± 0.014 as the baseline to beat. Not pinned by a test: the repo has no Playwright
  harness and adding one was out of scope.

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

Closed (2026-07-03, account-linking audit; superseded 2026-07-13 by the social-login
removal): **Google double-sign-up** — email-collision guard added to the Google path (parity
with GitHub), emails normalized on all ingest paths, the 409 surfaced in the frontend, and
`uq_users_email_lower` (migration 0007) backstopping at the DB. The provider paths (and their
consent-screen/provider-console go-live items) no longer exist; the email normalization + DB
index survive as the email/password invariant above. Existing pure-social accounts
(`password_hash IS NULL` with a provider sub) are locked out pending an operator decision —
count query in the social-login-removal PR body.

Closed (2026-07-03, user-auth audit remediation): **admin token separated from HMAC_SECRET**
(dedicated `ADMIN_API_TOKEN`, constant-time compare, fail-closed when unset — see admin table
above); **blocking logout** (`apps/web/lib/logoutClient.ts` gates client sign-out on the
backend session revocation — never a silent half-logout); **user PII cleared on sign-out**
(`rp_address_book`, `rsends.pendingMerge`, `rsend_antiphishing_code`, `rp_pending_queue`,
`rp_compliance_db` — cross-logout offline-first persistence consciously traded for
shared-device privacy).
