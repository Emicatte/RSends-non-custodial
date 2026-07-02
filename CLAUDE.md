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
  default bucket. `_get_merchant_id` raises 401 when there is no authenticated client; the only
  unauthenticated path into a merchant handler is the public checkout GET, which short-circuits
  to a bare 404 explicitly.

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
| `POST /payment-intent` (create) | write | Y — chain↔env check + env stamped on the intent | Y |
| `GET /payment-intent/{id}` | read | Y — `PaymentIntent.environment` filter | Y |
| `GET /transactions` (list) | read | Y — `PaymentIntent.environment` filter | Y |
| `POST /payment-intent/{id}/resolve` | write | Y — `PaymentIntent.environment` filter | Y |
| `POST /payment-intent/{id}/cancel` | write | Y — `PaymentIntent.environment` filter | Y |
| `POST /webhook/register` | write | Y — env stamped on the webhook | Y |
| `POST /webhook/test` | write | Y — `MerchantWebhook.environment` filter | Y |

Outbound webhook dispatch (`webhook_service.py`) also filters
`MerchantWebhook.environment == intent.environment` — test endpoints never receive live
events and vice versa.

### Known follow-ups (tracked here so they're not forgotten — do not fix as a drive-by)

- **Public checkout status GET is broken in production config.** The allowlisted
  unauthenticated `GET /payment-intent/{id}` (what `/pay` polls via
  `apps/web/app/api/pay/[intentId]/route.ts` with `X-Checkout-Public`) returns a bare 404 for
  every intent — it only works in dev because `RSEND_DEV_AUTH_BYPASS=1` makes every request
  client `"debug"`. Safe (no leak) but non-functional. Proposed fix: on unauthenticated +
  allowlisted GET, look up by `intent_id` alone and return a **limited public status view**
  (the route's documented intent: anyone with the link can view status) — product decision
  pending, separate change.
- **Error envelope inconsistency.** Middleware errors are flat `{error, message}` but route
  `HTTPException(detail={...})` responses get FastAPI-wrapped as `{detail: {...}}` — align in a
  dedicated docs/handler change.
- **Render provisioning before go-live:** Redis must be provisioned and `DEBUG=false` set —
  fail-closed rate limiting depends on both.

Closed (2026-07-02): environment filter on intent reads/mutates (PR #2, migration 0005);
webhook `environment` dimension incl. outbound dispatch (migration 0006); fail-closed
`_get_merchant_id` (401, no shared bucket). SQL-injection sweep verdict: parametrized
everywhere (ORM/bound params; only static `SELECT 1` probes and SQLite PRAGMAs outside it).
