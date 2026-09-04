# Integration contract — gaps and inconsistencies, 2026-08-12

Companion to `docs/INTEGRATION_CONTRACT.md`. That document is normative and citable; this
one is a work list and should be deleted when it is exhausted.

Two parts:

- **Part A** — commitments the contract makes that **no test enforces today**, ordered by
  how much it would hurt to break one without noticing. For each: add the test, or remove
  the promise. That call is the operator's.
- **Part B** — inconsistencies found while writing the contract, **not corrected**. The
  first group is the important one: promises that look obvious and are *already false*.

Nothing in this session changed code or tests.

---

## Part A — unenforced commitments, worst first

### 1. ~~The idempotency middleware has zero test coverage — and is actively broken~~ CLOSED 2026-09-04

**Fixed on `fix/idempotency-tenant-scope`.** The key is now
`(tenant, environment, path, idem_key)` (`idempotency.py:158`), where the tenant is the API
key's `client_id` or, on the session surface, the access token's `sub`; a request with no
derivable identity skips the cache rather than sharing one. The body fingerprint rides
**beside** the record, not in the key — in the key it would make a byte-different retry miss
and create the duplicate the mechanism exists to prevent — and a mismatch is
`409 IDEMPOTENCY_KEY_REUSED`. `FINANCIAL_PATHS` became `FINANCIAL_PATH_PREFIXES` with
`startswith`, which is what the parameterised `/{id}/cancel` and `/resolve` routes needed
(an exact-match set could never have matched them), and fail-closed now covers a failing
read and a failing lock, not only a null client. `tests/test_idempotency_tenant_scope.py`
pins all of it, including two controls proving the rejections are this layer's.

Two things this did NOT close, both deliberate:

- The tenant is the owner **wallet address**, not `org_id` — the same key
  `PaymentIntent.merchant_id` uses. Two orgs sharing an owner address still share a bucket.
  That moves with the org_id re-key, not before it.
- Session routes take `environment` as a **query param**, which is in neither the path nor
  the fingerprint. A session caller reusing one key across `?environment=test` and `=live`
  with an identical body would collide. Not reachable today: `/app` is test-locked and sends
  no idempotency key at all. Folding `request.url.query` into the fingerprint would close it.

*Original text follows.*

`app/middleware/idempotency.py`. A grep for `IdempotencyMiddleware` or `X-Idempotency-Key`
outside the module itself and `main.py` returns nothing. (`test_webhook_idem_rollback.py` is
about webhook delivery dedup — a different mechanism.)

This is not merely an untested promise. The cache key is

```python
cache_key = f"idem:{hashlib.sha256(f'{request.url.path}:{idem_key}'.encode()).hexdigest()}"
```

`app/middleware/idempotency.py:56` — **no merchant, no org, no environment, no HTTP method,
no body hash.** Two merchants POSTing to `/api/v1/merchant/payment-intent` with the same key
string inside the 24-hour TTL receive each other's full `PaymentIntentResponse`: `intent_id`,
`reference_id`, `recipient`, `metadata`, and `onchain.calldata`.

The value our own docs recommend is `X-Idempotency-Key: ORD-1024`
(`apps/web/app/docs/errors/page.tsx:146`). A plugin keyed on the WooCommerce order id
collides across stores on day one, and the failure mode is a payment intent pointing at
another merchant's settlement wallet.

Also unprotected: merchant paths are non-financial, so a Redis outage means idempotency
fails **open** (`:58-68`), and the in-flight lock degrades to "acquired" if the acquire
throws (`:90-91`).

**Recommendation:** scope the cache key by `client_id` and environment, and add a body
fingerprint. Then test it. Until that lands, the contract carries the burden as an
integrator obligation — which works, but only for integrators who read it.

### 2. No inventory test for error-envelope shapes

The contract's §6 promise — "no ninth shape appears" — is held up by nothing. There is no
test anywhere that enumerates the response shapes. Individually, shapes 3 (`500`), 4
(per-endpoint 429), 5 (global 429), 6 (route `detail` object) and 8 (Pydantic 422) are all
unpinned, as is the `403 INSUFFICIENT_SCOPE` body.

This is the promise most likely to be broken by an unrelated refactor, because adding a new
error shape feels like adding a feature.

### 3. `X-RSend-Delivery-Id` is referenced by zero tests

The header that every integrator dedupes on — that our own docs call "the whole retry
contract" (`apps/web/app/docs/webhooks/page.tsx:214-217`) — has no test covering its name,
its `{intent_id}:{event}:{webhook_id}` format, or its stability across retries. Renaming it
or changing its shape would break every integration in the field and fail nothing in CI.

Its *effect* is pinned indirectly (`test_webhook_enhanced.py::test_db_idempotency_no_duplicate`,
`test_webhook_idem_rollback.py::test_committed_delivery_stays_exactly_once`), but the wire
contract is not.

### 4. No key-set test for `PaymentIntentResponse` or `MerchantTransactionItem`

`test_webhook_contract.py` has `CONTRACT_KEYS` for the webhook payload and it works well.
The REST response — the more heavily used surface — has no equivalent. No test asserts
`set(response.keys()) == …` for either the single intent or the list item.

This is the cheapest high-value gap to close: it is the existing pattern, applied to two
more models.

### 5. No test covers any security header

Grep for `Content-Security-Policy` or `X-Frame-Options` across every test directory:
**zero hits**. `frame-ancestors 'none'` plus `X-Frame-Options: DENY`
(`apps/web/next.config.mjs:115, :119`) is the strongest promise in the contract — it is what
makes the popup integration shape permanent — and it is one careless edit to
`next.config.mjs` away from disappearing silently.

### 6. No viewport or rendering test on `/pay`

The §8 floor of 500 × 720 is unenforced. The only dimensional assertions in the repository
are two `minHeight` checks (`apps/web/app/__tests__/pay/checkoutSkeleton.test.tsx:69-70`).
There is no Playwright, no Cypress, no e2e config in the repo at all, and no overflow test.

See Part B — the constraint that sets this floor is a placeholder bug, so the honest fix
is to shrink the floor before pinning it.

### 7. The `amount` format in webhook payloads

Only one literal is pinned: `amount == "50.0"`
(`test_webhook_contract.py:212`), for one specific float. Nothing pins "always has a decimal
point", "never scientific notation", or any scale. Since `amount` is `str()` of a `Float`
column, there is currently no invariant to pin — which is itself the finding.

### 8. Retry count and backoff schedule — and a test that looks like coverage and isn't

Nothing asserts 5 attempts, nothing asserts the 120 / 480 / 1920 / 7680 second gaps, nothing
asserts the 10-second timeout. Only `next_retry_at > now`
(`test_webhook_enhanced.py::test_failure_schedules_retry`).

Worse: `MAX_RETRIES` and `BASE_BACKOFF_SECONDS` are **imported at
`tests/test_webhook_enhanced.py:35` and never referenced anywhere in the file.** Anyone
scanning imports concludes retry behaviour is covered. It is not.

### 9. Success is "2xx" but only 200 and 500 are exercised

`webhook_service.py:1213` defines success as `200 <= status < 300`. Tests cover 200
(delivered) and 500 (retry). 201, 202, 204, and every 3xx and 4xx are untested — including
the 3xx behaviour in Part B, which is a live footgun.

### 10. The `/pay` route itself

No test resolves `/pay/{intentId}`, no test asserts `/en/pay/{id}` 404s, and no middleware
test file exists. The i18n matcher exclusion (`apps/web/middleware.ts:96-98`) is what keeps
the URL shape stable, and it is unguarded.

### 11. The enumerated sets themselves

Nothing asserts the membership of `IntentStatus` (`app/models/merchant_models.py:30-39`),
of `VALID_EVENTS` (`:480-491`), or of `LatePaymentPolicy`. §4 of the contract promises that
no existing value is removed or renamed, and a deletion would pass CI.

The nearest thing that exists,
`test_webhook_contract.py::test_every_emitted_event_is_subscribable`, asserts a hardcoded
subset relationship rather than the set itself — see B.1, where it passes while the
invariant it describes is false.

### 12. Request validation on create-intent

Unpinned: the `currency` allowlist, the `expires_in_minutes` 5..1440 bounds, the `amount > 0`
check, the `recipient`/`expected_sender` regex and lowercasing, the `late_payment_policy`
allowlist, the `chain` default, and the fact that **unknown fields are silently ignored**.

(`test_security.py::TestCurrencyWhitelist` asserts the same six currency strings but against
`POST /api/v1/tx/callback`, a different schema. It is not coverage of this one.)

### 13. `Retry-After`, and the limits on `/transactions` and the webhook routes

`test_rate_limit_matching.py` pins four endpoint tuples. Not pinned: `GET /transactions`
(60/60), `POST /webhook/register` (5/hour), `POST /webhook/test` (10/60), the global per-key
limit, `Retry-After` on any 429, and the fail-closed 503 at middleware level.

### 14. Auth details

Unpinned: the `rsend_live_` prefix, the 48-hex key length, the case-sensitivity of the
`Bearer ` scheme token, and the `403 INSUFFICIENT_SCOPE` response body.

---

## Part B — inconsistencies found, not corrected

### B.1 Obvious promises that are already false

These are the ones worth reading first. Each is something a reasonable person would assume
is true, and is not.

**Idempotency is not tenant-scoped.** Covered above as A.1. It belongs in both lists: it is
an unenforced promise *and* an active defect.

**The `test` event is not in the event allowlist, and it ignores your subscription.**
`_build_payload("test", …)` emits `{"event": "test"}` and `send_test_event` POSTs it
directly (`app/services/webhook_service.py:1327-1331`), bypassing both `VALID_EVENTS`
(`app/models/merchant_models.py:480-491`) and the per-endpoint `events` filter. A merchant
registered for `["payment.completed"]` receives it anyway. The test that names this
invariant — `test_webhook_contract.py::test_every_emitted_event_is_subscribable` — checks a
**hardcoded** eight-name list that omits `test`, so it passes while the invariant it
describes is false.

**"The test event is byte-shape-identical to a real event" is true for keys and false for
values and headers.** `_build_test_event_payload` (`webhook_service.py:1279-1290`) builds a
`PaymentIntent` that is never added to a session, so SQLAlchemy's Python-side column
defaults never fire. `amount_received` is `null` in the test event and `"0"` in every real
one; `late_minutes` and `reference_id` likewise differ. And the headers differ structurally:

- the test-fire's `X-RSend-Delivery-Id` is `test:{webhook_id}:{iso8601}`
  (`webhook_service.py:1322`) — a different shape from the production
  `{intent_id}:{event}:{webhook_id}`, with colons *inside* the third field, so a naive
  `split(":")` parser breaks on it;
- the test-fire **omits `X-RSend-Delivery` entirely** (`:1316-1323`), which real deliveries
  always send.

A handler that validates the documented header set rejects the test event and accepts
production traffic — precisely inverting what the button is for.

**The body `timestamp` and the `X-RSend-Timestamp` header are different clocks.** The body
value is frozen at build time and persisted (`:1098` → `:1046`); the header is recomputed on
every attempt (`:1188`). After the ~2 h 08 m backoff they differ by that much. A merchant
who validates freshness against the body — a plausible reading of the docs example, which
shows a 300-second check — rejects every retry.

**Registering with `"events": []` produces a firehose endpoint.** The validator iterates the
list, so an empty list passes trivially (`merchant_models.py:509-515`). The dispatch filter
is `if wh.events and event not in wh.events` (`webhook_service.py:1026`, `:1407`) — a falsy
list means *receive everything*, including events never opted into.

**There is no delivery ordering, at all.** `process_pending_deliveries` has no `ORDER BY`
(`webhook_service.py:1133-1139`) and each delivery has independent backoff. Meanwhile the
builder's own comment (`:1078-1079`) tells merchants they can order events "e.g. paid before
reversed" via `event + timestamp`. They cannot: `payment.completed` and `payment.reversed`
are separate rows with separate schedules.

**A 3xx response is fatal.** `httpx.AsyncClient` is built with only `timeout=`
(`webhook_service.py:1203`), so `follow_redirects` defaults to `False`. A merchant who moves
their endpoint and leaves a `301` behind burns all five attempts over ~2 h 50 m and the
delivery dies. There is no alert on permanent failure and no replay endpoint.

**`review` is unreachable, so `POST /payment-intent/{id}/resolve` is a dead endpoint.**
`IntentStatus.review` is written only at `webhook_service.py:377, 913, 922, 926`, all inside
`_handle_late_payment` / `match_and_complete_intent` / `match_transaction_to_intent` /
`finalize_match` / `_complete_intent` — every one of which has zero callers outside its own
module and the tests. So `resolve` can only return `400 INVALID_STATE`
(`merchant_routes.py:438-445`), and `completed`, `refunded`, `partial`, `overpaid` are
transitively unreachable. **Five of nine statuses cannot occur**; `completed` nonetheless
exists on legacy rows, and `invoice_service.py:72` reads both.

**`GET /payment-intent/{id}` performs a write.** It flips a `pending` intent past its expiry
to `expired` and commits (`merchant_routes.py:230-236`). A "just check the status" poll is a
mutation. The public payer view deliberately does not persist
(`app/api/public_routes.py:55-65`), so the two endpoints can transiently disagree about
whether the flip has been durable.

**The split branch of `onchain` reports `routerVersion: 1`.** The split builder dict omits
the key (`app/services/router_registry.py:547-573`), so Pydantic's default of `1`
(`merchant_models.py:430`) fills in — while `router` points at the split router and
`function` is `paySplit`/`paySplitNative`. A client that forks its ABI on `routerVersion`,
which the field's own comment says is its purpose, picks the wrong one unless it checks
`split` first.

**`Bearer` is compared case-sensitively.** `auth.startswith("Bearer ")`
(`app/security/api_keys.py:155`), contrary to RFC 7235. A client that normalises the scheme
gets a bare 401 with no diagnostic.

**Scope is a blocklist, not an allowlist.** `api_auth.py:55` rejects only the literal
`"read"`, and only on non-GET. `scope` is an unconstrained `String(16)`
(`app/models/api_key_models.py:48`) with the `KeyScope` enum not bound to the column, so a
typo'd or future scope value receives full write access. On GET, scope is not checked at
all.

**The 396 px loading placeholder does not fit the card at any desktop width.** The card's
content box is 394 px for any viewport ≥ 640 px
(`460 − 2×32 − 2`, `apps/web/app/pay/_components/payUi.tsx:114, :118`), while
`CheckoutSkeleton.tsx:41` renders a fixed `width={396}`. It overflows by 2 px, invisibly,
because of `overflow-x: hidden` (`apps/web/app/globals.css:38`). Below ~487 px viewport it
is clipped severely.

The widest hard constraint on the checkout is therefore **a placeholder, not real content** —
real content fits in about 330 px. **Shrinking that one literal to ~380 would drop the
promised rendering floor from 500 to roughly 400.** The problem is the page, not the
document; the contract promises 500 because that is what is true today.

### B.2 Published documentation contradicting the code

All in `apps/web/app/docs/`.

| Where | Published | Actual |
|---|---|---|
| `webhooks/page.tsx:195-205` | first retry at 30 s, then 2 m / 8 m / 32 m / 2 h; "up to 5 retries" | 2 m / 8 m / 32 m / ~2 h 08 m; 4 retries after 1 immediate attempt. The 30 s slot **cannot occur**: `delivery.retries` is incremented at `webhook_service.py:1246`, *before* `30 * 4**retries` is computed at `:1257`. Already flagged internally in `webhook-integration-brief.md`, still shipping. |
| `webhooks/page.tsx:120` | `"status": "completed"` in the `payment.completed` example | `"paid"` |
| `webhooks/page.tsx:111` | `"amount": "100"` | `str(float)` cannot produce that — it yields `"100.0"`. An integrator writing a `^\d+$` parser breaks on the first real event. |
| `errors/page.tsx:26-55` | "two wrappings" plus a special case, and `body.detail ?? body` "covers every response" | Eight shapes. On the Pydantic 422, `detail` is an **array**, so `e.error` is `undefined`. It degrades rather than throwing, but the claim is false. |
| `errors/page.tsx:68`, `authentication/page.tsx:92` | `company_profile_required` listed as a merchant API error | The merchant router cannot emit it. It comes only from the session/JWT surfaces (`app/api/deps/require_org_approved.py:79`, `app/api/organizations_routes.py:201`). |
| `reporting/page.tsx:35` | `partial` and `overpaid` among the filterable statuses | Both unreachable. |
| `errors/page.tsx:121` | "429 with a `retry_after` value in seconds" | True for one of the three 429 bodies. |

And one message inside the backend itself: `INVALID_STATUS` lists the valid filter values as
"pending, completed, expired, cancelled, review, refunded, partial, overpaid"
(`app/services/intent_service.py:249-253`) — **omitting `paid`**, which is the only status
that matches genuinely settled intents. `?status=paid` works. The same omission is in the
OpenAPI description at `merchant_routes.py:369`.

### B.3 Duplication and dead code that a contract cannot survive

- **Two `intent_id` generators.** The live one is `intent_service.py:363`; a byte-identical
  dead copy sits at `merchant_routes.py:113-115` with no callers. Two generation sites for
  the one identifier the contract pins is exactly the drift a contract cannot absorb.
  `generate_reference_id` and `resolve_recipient` are likewise imported into
  `merchant_routes.py:36, :46` and never used there.
- **`match_confidence`** (`merchant_models.py:466`) is in the response model and populated
  by nothing. Permanently `null`.
- **`network`** is accepted by the request schema and discarded
  (`intent_service.py:406, :417`).
- **`request.state.testnet_only`** is set at `api_auth.py:76-77` and read nowhere.
- ~~**`FINANCIAL_PATHS` dead branch:** `idempotency.py:47` guards a block whose body is only a
  comment, and the nested `"alchemy" in request.url.path` check at `:49` can never be true
  given `FINANCIAL_PATHS = {"/api/v1/tx/callback"}`.~~ Removed 2026-09-04 with item 1.
- **`process_pending_deliveries`** assigns `success = await _attempt_delivery(...)` and never
  uses it (`webhook_service.py:1156`); the inactive-webhook branch marks the row failed
  without incrementing `processed`, so the returned count under-reports.
- **Two independently maintained token allowlists.** `EURC` is `enabled: true` in
  `app/token_registry.json` for chains 1 and 8453 but is absent from the Pydantic `currency`
  allowlist (`merchant_models.py:371`) → 422 before the registry is consulted. Conversely
  `cbBTC` and `DEGEN` pass Pydantic and are in **no** chain's registry → guaranteed 400
  `UNSUPPORTED_TOKEN`.
- **`X-Frame-Options: SAMEORIGIN`** in the backend's nginx config
  (`services/backend/nginx/nginx.conf:39`) against `DENY` in the web app
  (`apps/web/next.config.mjs:119`). Different hosts, so not a live bug — but a hazard if the
  contract ever says "our headers" generically.

### B.4 The documented base URL is not the API

`https://pay.rsends.io/api/backend/...` (`apps/web/app/docs/quickstart/page.tsx:41-43`) is a
Next.js catch-all proxy, `apps/web/app/api/backend/[...path]/route.ts`. It materially changes
the contract and **has no test coverage**:

- **Request headers are allowlisted** (`:33-46`): only `content-type, accept, x-wallet-*,
  x-timestamp, x-idempotency-key, x-chain-id, authorization` survive.
- **Response headers are destroyed** (`:115-118`): only `Content-Type` is re-emitted.
  `Retry-After`, `X-RateLimit-*`, `X-Request-ID`, `X-Correlation-ID` and
  `X-Idempotency-Replayed` never reach the caller.
- It adds a **ninth error shape** that exists nowhere in the backend:
  `502 {"error": "BACKEND_UNREACHABLE", "message": …}` on a 25-second edge timeout
  (`:120-127`), plus `404 {"error": "NOT_FOUND"}` for deny-listed prefixes (`:66`).

**This blocks the versioning policy.** A client-declared version header would be dropped on
the way in, and `Deprecation`/`Sunset` would be stripped on the way out. Both halves of the
deprecation channel are inert until this proxy forwards them.
