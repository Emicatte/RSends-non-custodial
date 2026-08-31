# RSends integration compatibility contract — v1

**Status: normative.** This is the authoritative copy. Breaking anything promised here is a
review stop, not a judgement call.

Last verified against the code on **2026-08-12** (`main`, tip `6c79e8d9`). Every promise in
this document carries a `file:line` anchor. Nothing here was taken from the public
documentation site — at the time of writing that site disagrees with the code in at least
seven places.

---

## Why this document exists

Our backend and our web app update whenever we want. An integration does not. A WooCommerce
plugin, a Shopify app, someone's custom middleware — these run on servers we do not control,
at the version the merchant installed, for months, and we cannot force an upgrade.

That turns every detail an integrator relies on into a permanent constraint. This document
records which details those are, while the installed base is still zero and the promise is
free.

**A commitment no test verifies breaks silently.** So each promise below carries a coverage
verdict: either the test that pins it, or ⚠ **NOT ENFORCED**. The unenforced ones are real
promises — we intend to keep them — but they are held up by intent alone today. They are
tracked, ranked by blast radius, in `contract-gaps-2026-08-12.md`.

### Scope

**In scope:**

| Surface | Where |
|---|---|
| Merchant API-key routes (7) | `/api/v1/merchant/*` — `services/backend/app/api/merchant_routes.py:69-73` |
| Public payer view of an intent | `GET /api/v1/public/payment-intent/{intent_id}` — `app/api/public_routes.py:76` |
| Outbound webhooks | `app/services/webhook_service.py` |
| Hosted checkout page | `apps/web/app/pay/[intentId]/` |

**Out of scope:**

- Session/dashboard routes under `/api/v1/user/org/*`. These are first-party surfaces for
  our own UI and move with the dashboard.
- **Anything mainnet.** No mainnet router is deployed and there is no self-service path to
  a `rsend_live_` key. Nothing in this document is a promise about live traffic.
- Deployment configuration: hostnames, DNS, TLS termination, CDN behaviour.

Every successful response on the merchant API is **`200`**, never `201`. No route sets
`status_code=`.

---

## Your half of the contract

Half of what follows is only freezable because the integrator agrees to be a tolerant
reader. If your client does not do these five things, we cannot promise the rest.

1. **Ignore what you do not recognise.** New keys in webhook payloads, new optional fields
   in responses, and **new enumerated values** may appear at any time, in a patch release,
   without notice. A client that throws on an unknown status or an unknown event name is
   broken by design. Branch on the values you know, default-case everything else.

2. **`X-Idempotency-Key` must be globally unique — not unique within your store.** This is
   an obligation, not a suggestion. The cache key is derived from the request path and your
   key string only (`app/middleware/idempotency.py:56`); it is **not** scoped by merchant,
   environment, or request body. Two integrations that both send `ORD-1024` to
   `/api/v1/merchant/payment-intent` within 24 hours will receive **each other's payment
   intent**, including the other party's recipient address and calldata. Namespace your key
   with something globally unique — an installation UUID, not an order number. See §10.

3. **Compare `chain` case-insensitively.** The value you send is stored and echoed back
   verbatim (`app/services/intent_service.py:415`, `merchant_routes.py:131`). Send `"BASE"`,
   get `"BASE"`. Send `"base"`, get `"base"`. Both are the same chain.

4. **Treat `paid` and `completed` as the same terminal success.** `paid` is what the live
   settlement path writes; `completed` is a legacy value that still exists on older rows and
   that our own code reads alongside `paid` (`app/services/invoice_service.py:72`).

5. **Deduplicate webhook deliveries on `X-RSend-Delivery-Id`, and make your handler
   idempotent.** Delivery is at-least-once and unordered. See §2.

---

## §1 — Webhook payload

### We promise

**The 21 base keys are always present, on every event.** A key is never omitted; a missing
value is JSON `null`. The builder is a single dict literal
(`app/services/webhook_service.py:1076-1101`), so this is structural, not incidental.

| Key | Type | Notes |
|---|---|---|
| `event_id` | string | `evt_` + 32 lowercase hex. Stable across retries of the same event. |
| `event` | string | The event name. |
| `intent_id` | string | |
| `reference_id` | string \| null | |
| `onchain_invoice_id` | string \| null | `0x`-prefixed bytes32. |
| `amount` | **string** | See "We do not promise" below before you parse this. |
| `amount_received` | string \| null | |
| `overpaid_amount` | string \| null | |
| `underpaid_amount` | string \| null | |
| `currency` | string | |
| `chain` | string | Canonical lowercase here (unlike the REST response — see §3). |
| `chain_id` | **integer \| null** | |
| `recipient` | string \| null | **null on split intents.** |
| `tx_hash` | string \| null | |
| `status` | string | An `IntentStatus` value — see §4. |
| `completed_late` | boolean | Never null. |
| `late_minutes` | integer \| null | |
| `metadata` | object \| null | Your metadata, passed through unchanged. |
| `timestamp` | string | ISO-8601 with a `+00:00` offset. |
| `created_at` | string \| null | ISO-8601. |
| `completed_at` | string \| null | ISO-8601. |

Three keys were removed from an earlier shape and **stay removed**: `fee`, `network`,
`merchant_id`.

**Exactly one payload builder exists**, and settlement events, lifecycle events and the
test-fire all go through it. We will not grow a second one.

Per-event additions, merged on top of the base set:

| Event | Adds |
|---|---|
| `payment.completed` | `tx_hash`, `settlement: "onchain"`, and `split` **only when the settlement has split legs** (`app/services/payment_indexer.py:940-947`) |
| `payment.reversed` | `tx_hash`, `reason: "reorg"`, `settlement: "onchain"` (`payment_indexer.py:1026-1035`) |
| `payment.expired`, `payment.completed_late`, `test` | nothing |

### We do not promise

- **The format of `amount`.** It is `str()` applied to a Python float from a `Float` column
  (`webhook_service.py:1085`, `app/models/merchant_models.py:101`). Today that yields
  `"50.0"` for 50. It can in principle yield `"0.30000000000000004"`, and for very large or
  very small values, scientific notation. **Parse it as a decimal string; do not assume a
  scale, do not assume a decimal point is present or absent, and do not regex it as
  `^\d+$`.** The public docs example showing `"amount": "100"` is a value this code cannot
  produce.
- **The exact bytes of the body.** Serialization is `json.dumps(payload, default=str)`
  (`webhook_service.py:1185`) — Python's default separators (a space after `,` and `:`), no
  `sort_keys`, `ensure_ascii` on. Key order follows the builder, with merged extras
  appended. If you compute your own digest over the body, do it over the bytes you
  received, never over a re-serialization.
- **That `chain_id` is non-null.** For a chain outside the registry it is `null`
  (`app/services/router_registry.py:131-132`) while `chain` remains a string.
- **That `recipient` is non-null.** It is `null` for split intents by design
  (`merchant_models.py:164-166`).
- **That a per-event extra will not shadow a base key.** Extras merge last
  (`webhook_service.py:1102-1103`).

### Enforced by

`tests/test_webhook_contract.py::test_every_event_emits_the_contract_shape` (8
parametrized events, asserts the exact key set),
`::test_wire_body_shape_and_signature_settlement_path` (asserts it on the **captured wire
bytes**), `::test_dispatch_event_lifecycle_path_same_shape` (on the persisted payload),
`::test_test_fire_payload_matches_production_shape`, `::test_exactly_one_builder_exists`,
`::test_indexer_finalize_extras_carry_no_fee_or_chain_id` (extras ⊆
`{tx_hash, settlement, split}`), `::test_contract_types_and_canonical_chain`,
`tests/test_webhook_enhanced.py::TestPayloadStructure::test_payload_contains_required_fields`.

⚠ **NOT ENFORCED:** the format of `amount`; the nullability of 16 of the 21 keys;
`chain_id` being null on an unknown chain; `recipient` being null on splits; key order;
the serialization form.

---

## §2 — Webhook signature and delivery

### We promise

**Signature.** HMAC-SHA256 (`webhook_service.py:261-265`), keyed with the per-endpoint
secret (64 hex, issued once at registration, `:184`). The signed string is

```
"{timestamp}." + <raw body bytes>
```

— one ASCII `.`, no version prefix, no `v1=` scheme label. The digest is **lowercase hex**,
64 characters, bare.

**The bytes we sign are exactly the bytes we send.** The body is serialized once and passed
to both the signer and the HTTP client as `content=` (`webhook_service.py:1185-1206`). Verify
over the raw request body; never re-serialize.

**Headers**, spelled exactly this way:

| Header | Value | Stable across retries? |
|---|---|---|
| `X-RSend-Signature` | lowercase hex HMAC | no (timestamp changes) |
| `X-RSend-Timestamp` | unix **seconds**, decimal string | no — recomputed per attempt |
| `X-RSend-Event` | the event name | yes |
| `X-RSend-Delivery-Id` | `{intent_id}:{event}:{webhook_id}` | **yes — dedupe on this** |
| `X-RSend-Delivery` | a fresh UUID | **no — do not dedupe on this** |
| `User-Agent` | `RSend-Webhook/1.0` | yes |

`X-RSend-Delivery-Id` is backed by a `unique=True` column
(`merchant_models.py:253`), so one delivery row exists per (intent, event, endpoint).
`event_id` in the body is likewise stable across retries.

**Success is any 2xx** (`webhook_service.py:1213`). Registration requires HTTPS and rejects
loopback, private, link-local, reserved and non-global addresses — both at registration
(422 `WEBHOOK_URL_FORBIDDEN`) and again immediately before every single delivery attempt
(`webhook_service.py:120-161`, `:1174-1183`).

### We do not promise

- **That we enforce the 300-second freshness window.** `WEBHOOK_FRESHNESS_SECONDS = 300`
  (`webhook_service.py:244`) is the default tolerance of the *reference verifier* we ship
  for merchants (`:274`, `:299-300`). The sender never calls it. It is a convention for your
  receiver, and it works because we stamp a fresh timestamp on every attempt — but it is not
  a sender-side invariant.
- **Any delivery ordering.** The retry sweep has **no `ORDER BY`**
  (`webhook_service.py:1133-1139`) and every delivery carries an independent backoff. A
  `payment.reversed` can arrive **before** the `payment.completed` it reverses. Drive your
  state machine from your own order state, never from event arrival order.
- **That we follow redirects.** The HTTP client is constructed without `follow_redirects`
  (`webhook_service.py:1203`), so httpx's default of `False` applies. **A 301/302/307/308 is
  a failure**, burns a retry, and after the last attempt the delivery is permanently dead.
  If you move your endpoint, register the new URL — do not leave a redirect.
- **The retry schedule or attempt count.** Today: 5 total attempts, with gaps of 2 m, 8 m,
  32 m and ~2 h 08 m (`webhook_service.py:1246-1258`), a 10-second timeout, and a ~2 h 50 m
  total window. These are operational tuning and may change.
- **That the body's `timestamp` matches `X-RSend-Timestamp`.** The body value is frozen when
  the event is built and persisted; the header is recomputed per attempt. On a retry they
  differ by the whole backoff. **Validate freshness against the header, never the body.**

### Enforced by

`tests/test_webhook_signing.py` — `::test_sent_webhook_signed_with_real_secret_verifies`,
`::test_placeholder_and_wrong_secret_rejected`, `::test_tampering_invalidates_signature`,
`::test_stale_timestamp_rejected_even_with_valid_hmac` (the 300 s window, verifier side),
`::test_payment_reversed_signed_with_real_secret`,
`::test_signature_derives_from_webhook_secret_not_global`,
`::test_outbound_modules_do_not_import_inbound_signer`.
`tests/test_webhook_contract.py::test_wire_body_shape_and_signature_settlement_path`
(signature verifies over the captured wire bytes).
`tests/test_webhook_enhanced.py::TestWebhookDelivery::test_immediate_delivery_success`
(`X-RSend-Signature` and `X-RSend-Event` by literal name).
Egress: `tests/test_webhook_session_register_test.py::test_check_webhook_egress_blocks`
(parametrized), `::test_register_ssrf_blocks_private_ip`,
`::test_send_test_event_blocks_private_host_no_request`,
`tests/test_webhook_egress_loopback_escape.py` (5 tests).
Exactly-once dispatch: `tests/test_webhook_signing.py::test_concurrent_finalize_fires_paid_exactly_once`,
`::test_concurrent_reverse_fires_reversed_exactly_once`.

⚠ **NOT ENFORCED — and this is the largest single gap in this document:**
**`X-RSend-Delivery-Id` is referenced by zero tests.** Its name, its
`{intent_id}:{event}:{webhook_id}` format, and its stability across retries are pinned by
nothing, despite being the pivot of every integrator's deduplication. Also unenforced:
lowercase hex; 2xx as a *range* (only 200 and 500 are exercised); redirects not being
followed; the retry count and backoff values; the 10 s timeout; `Content-Type`;
`User-Agent`; the egress re-check before each attempt.

---

## §3 — Creating a payment intent

`POST /api/v1/merchant/payment-intent`

### We promise

**Request field names, requiredness and bounds** (`app/models/merchant_models.py:311-394`):

| Field | Type | Required | Default | Bounds |
|---|---|---|---|---|
| `amount` | float | **yes** | — | `> 0`, and its decimal scale must not exceed the token's `decimals` for the requested `(chain, currency)` — 6 for USDC/USDT/EURC, 18 for ETH/DAI. `10.000001` USDC is accepted; `10.0000001` is `400 AMOUNT_PRECISION_EXCEEDED`. We reject rather than round, because rounding would invoice a value you did not ask for. |
| `currency` | string | **yes** | — | case-sensitive member of `{ETH, USDC, USDT, DAI, cbBTC, DEGEN}` |
| `chain` | string | no | **`"BASE"`** | — |
| `expires_in_minutes` | integer | no | `30` | `5..1440` |
| `recipient` | string \| null | no | `null` | EVM `^0x[a-fA-F0-9]{40}$` (lowercased on ingest) **or**, on a watch-only chain, a base58check address (e.g. TRON `T…`) validated by checksum and stored **case-preserved** |
| `expected_sender` | string \| null | no | `null` | same rule as `recipient` |
| `metadata` | object \| null | no | `null` | free-form |
| `split` | array \| null | no | `null` | 2..20 legs, no duplicate addresses, `share_bps` sums to exactly 10000, mutually exclusive with `recipient` |
| `late_payment_policy` | string | no | `"auto"` | `{reject, auto, review}` |
| `amount_tolerance_percent` | float | no | `1.0` | `0.0..10.0` |
| `allow_partial` | boolean | no | `false` | |
| `allow_overpayment` | boolean | no | `true` | |

> **`chain` defaults to `"BASE"`, which is mainnet.** Always send it explicitly. A
> `rsend_test_` key that omits it gets `400 TESTNET_ONLY`.
>
> **`TRON` is mainnet-only** (watch-only settlement, TRON mainnet). A `rsend_test_` key
> asking for it gets `400 TESTNET_ONLY`; `nile`/`shasta` are not supported at all.

**Identifier formats.** `intent_id` is `pi_` + 32 lowercase hex — `secrets.token_hex(16)`,
128 bits of CSPRNG (`app/services/intent_service.py:363`). This is load-bearing: the hosted
checkout's access model is id-as-secret. `reference_id` is exactly 16 lowercase hex
(`merchant_models.py:58-67`). `onchain_invoice_id` is a `0x`-prefixed bytes32.

**Response completeness.** `PaymentIntentResponse` is declared without `exclude_none`, so
**every field is always present**; nullable ones carry `null`. Same for the nested `onchain`
object: all 19 of its keys are always present, because it is validated through a Pydantic
model with defaults (`merchant_models.py:411-445`).

**`onchain` is `null`** when there are no router instructions to give. Conditions
(`router_registry.py:528-529` and `:549-550`): the chain has no known chain-id; **no router is
configured for that chain**; the token is not in that chain's registry; or the intent is a
split and no split router is configured.

> **`onchain: null` is no longer always an error.** It has two meanings now, and `chain` tells
> them apart. On a **router chain** it still means the intent is unpayable — treat it as a hard
> error. On a **watch-only chain** it is the normal, expected shape: there is no contract to
> call because the payer sends the token **directly to `recipient`**, and the indexer observes
> the transfer. `TRON` is the first such chain. A watch-only intent also carries
> `onchain_invoice_id: null` — no contract will ever emit one — so do not use that field's
> presence as a payability signal either. **Branch on `chain`, not on `onchain == null`.**

### We do not promise

- **That unknown request fields are rejected.** There is no `model_config` anywhere in the
  request models, so Pydantic v2's default `extra='ignore'` applies: a field we do not know
  is silently dropped and you get a `200`. Do not use an unknown field as a channel; use
  `metadata`.
- **That `network` does anything.** It is accepted by the schema and **discarded**; the
  stored value is derived from the chain (`intent_service.py:406, :417`).
- **`match_confidence`.** It is declared in the response model and populated by no code path.
  It is always `null`.
- **That `GET /transactions` returns the same shape as the single GET.** The list item is a
  strict subset that **omits `reference_id` and `onchain`**
  (`merchant_models.py:594-613`). You cannot reconcile from the list alone if you need
  either.
- **That reading an intent is side-effect-free.** `GET /payment-intent/{id}` flips a
  `pending` intent past its expiry to `expired` and commits
  (`merchant_routes.py:230-236`). The public payer view deliberately does not persist
  (`public_routes.py:55-65`).

### Enforced by

`tests/test_intent_split_gate.py::test_create_rejects_bps_sum_not_10000`,
`::test_create_rejects_bad_split_shapes`, `::test_split_and_recipient_mutually_exclusive`,
`::test_split_unavailable_without_router_config`.
`tests/test_intent_network_normalization.py` (4 tests — `network` derived, merchant value
discarded).
`tests/test_merchant_chain_gate.py` (chain gating, `TESTNET_ONLY`/`MAINNET_ONLY`),
`tests/test_creation_token_gate.py` (3 tests — unregistered and disabled tokens rejected
with no row persisted), `tests/test_recipient_gate.py` (5 tests — the 422s and the
settlement-wallet resolution).
Amount precision: `tests/test_tron_watchonly_intent.py` (over-scale rejected on base and on
tron, an amount that would convert to 0 base units rejected, and an accepted amount asserted to
survive `to_base_units` without rounding).
`onchain` branches: `tests/test_fee_model.py::TestBuildOnchainPayment::test_includes_fee_total_maxfee_and_calldata`,
`::test_degrades_when_quote_unavailable`, `tests/test_router_v2.py` (v2 branch, v2 wins over
v1, v1 still reports `routerVersion 1`).
Watch-only chains: `tests/test_tron_watchonly_intent.py` (base58 recipient round-trips
byte-identical; `onchain` is null without a 422; `onchain_invoice_id` is null; the chain↔
address-family gate; TRON classified live, not test).
Environment binding: `tests/test_merchant_env_isolation.py::test_create_stamps_key_environment`,
`::test_get_intent_blocked_across_environment`, `::test_list_transactions_scoped_to_environment`.

⚠ **NOT ENFORCED:** the complete key set of `PaymentIntentResponse` and of
`MerchantTransactionItem` — there is no `set(keys()) ==` assertion for either, unlike the
webhook payload; the `reference_id` format; the `intent_id` entropy; the split branch of
`onchain`; the `currency` allowlist; the
`expires_in_minutes` bounds; extra-field tolerance.

---

## §4 — Enumerated values

### We promise

**No existing value is removed or renamed.** That applies to intent statuses
(`merchant_models.py:30-39`), webhook event names (`VALID_EVENTS`, `:480-491`), and the
error codes in §6.

**Intent statuses** — the full set of nine: `pending`, `paid`, `completed`, `expired`,
`cancelled`, `review`, `refunded`, `partial`, `overpaid`.

**Event names** — the full set of ten: `payment.completed`, `payment.completed_late`,
`payment.expired`, `payment.expired_rejected`, `payment.needs_review`, `payment.cancelled`,
`payment.partial`, `payment.overpaid`, `payment.ambiguous`, `payment.reversed`.

### We do not promise

**That all of them can occur.** New values may be added at any time — that is your side of
the contract, §"Your half", item 1 — and several existing ones are currently unreachable.
Honest reachability today:

| Statuses that actually occur | `pending`, `paid`, `expired`, `cancelled`, and — on watch-only chains only — `partial` |
|---|---|
| Unreachable | `review` is written only by a matcher with zero production callers (`webhook_service.py:377, 913, 922, 926`). `completed`, `refunded` and `overpaid` all require passing through `review` first, so they are transitively unreachable. `completed` does still exist on legacy rows. |

**`partial` became reachable on 2026-08-29**, on watch-only chains (TRON) only
(`app/services/tron_matcher.py`). There is no router and no escrow on such a chain, so an
underpayment has already arrived in the merchant's wallet and cannot be refused: the intent
moves to `partial` and carries `amount_received` + `underpaid_amount`. It does **not** pass
through `review`, and it is **terminal for now** — partial payments do not accumulate, so a
second transfer completing the amount does not close the invoice. On router chains
(EVM), an underpayment is still refused on-chain and `partial` still cannot occur.

Because `review` is unreachable, **`POST /payment-intent/{id}/resolve` can only ever return
`400 INVALID_STATE`** (`merchant_routes.py:438-445`).

| Events that actually fire | `payment.completed`, `payment.reversed`, `payment.expired`, `test`, and — on watch-only chains only — `payment.partial` and `payment.ambiguous` |
|---|---|
| Never fired | `payment.cancelled` is a reserved placeholder. `payment.expired_rejected`, `payment.needs_review` and `payment.overpaid` come only from the dead matcher. `payment.completed_late` requires `review`, so in practice it does not fire either. |

**Four of the ten event names are subscribable and will never arrive.** Subscribe to what you
need; do not build logic that waits on the others.

**`payment.partial` and `payment.ambiguous` became reachable on 2026-08-29**, on watch-only
chains (TRON) only (`app/services/tron_matcher.py`):

- **`payment.partial`** — the payer sent less than the invoice. The intent is `partial`, not
  `paid`; `amount_received` and `underpaid_amount` are populated (both in **token** units,
  like `amount`). The money is already at the merchant.
- **`payment.ambiguous`** — one transfer could be paying more than one of your pending
  invoices **and the amount does not settle it**, so we will not guess. Where exactly one of
  those invoices asks for precisely the amount that arrived, that invoice is paid and you get
  `payment.completed` instead (`tron_matcher._sole_exact_match`, pinned by
  `test_tron_matching.py::test_two_candidates_the_one_asking_the_exact_amount_wins`); this
  event is what remains — no candidate matches the amount exactly (a partial payment against
  several open invoices), or several do (two invoices for the same amount). It therefore
  fires strictly less often than before 2026-08-31, never more. **No intent was modified**;
  the `intent_id` in the payload is one representative candidate, and the full list is in the
  extra key `candidate_intent_ids`. Reconcile by hand. Note that overpayment does **not** produce
  `payment.overpaid`: an overpaid invoice is satisfied, so it fires `payment.completed` with
  `overpaid_amount` set.

Note this is the first path in production that populates `amount_received`,
`overpaid_amount` and `underpaid_amount` at all — they have carried `"0"`/`null` on every
event until now. Their type is unchanged (**string \| null**).

One asymmetry worth naming: **`test` is emitted but is not in `VALID_EVENTS`, and it bypasses
your subscription list** (`webhook_service.py:1327-1331`). If anyone presses "Send test" you
will receive an `event: "test"` body even if you only subscribed to `payment.completed`.
Handle it or ignore it, but expect it.

### Enforced by

`tests/test_webhook_contract.py::test_every_emitted_event_is_subscribable` — but it checks a
**hardcoded** list of eight names, so it cannot catch a new emit site, and it does not catch
`test`.
`tests/test_webhook_contract.py::test_finalize_event_type_maps_review_to_needs_review`.

⚠ **NOT ENFORCED:** the `IntentStatus` member set; the `VALID_EVENTS` set; which values are
reachable; the `LatePaymentPolicy` values.

---

## §5 — Authentication

### We promise

**Key format.** `rsend_test_` or `rsend_live_` followed by **48 lowercase hex characters**
(`secrets.token_hex(24)`), 59 characters in total
(`app/security/api_keys.py:115-130`). Keys are bcrypt-hashed at rest and the plaintext is
shown exactly once.

**Header scheme: `Authorization: Bearer <key>`, and nothing else.** There is no `X-API-Key`
anywhere in this codebase and there never was.

> The scheme token is compared **case-sensitively**: `auth.startswith("Bearer ")`
> (`api_keys.py:155`). RFC 7235 says the scheme is case-insensitive; this backend disagrees.
> Send exactly `Bearer ` with a capital B. A client library that normalises the scheme to
> lowercase gets a bare `401` with no diagnostic.

**Scopes.** `read` | `write` | `admin`, enforced by HTTP method: any non-GET with a `read`
key returns `403 INSUFFICIENT_SCOPE` (`app/middleware/api_auth.py:55-62`).

**Environment binding.** `rsend_test_` keys act only on test data, `rsend_live_` only on
live, on **both reads and writes**. Intents and webhooks carry an `environment` column
stamped at creation and filtered on every lookup, and outbound dispatch filters by it too.
A test endpoint can never receive a live event.

**The KYB gate covers the entire merchant router**, as a router-level dependency
(`merchant_routes.py:69-73`) — not per-route, so it cannot be forgotten on a new route.

### We do not promise

- **That scope is an allowlist.** The check rejects only the literal string `"read"`, and
  only on non-GET (`api_auth.py:55`). Any other scope value gets write access, and **scope
  is not checked at all on GET requests**.
- **`client_id` stability across a re-key.** It equals the owner wallet address today.

### Enforced by

`tests/test_merchant_fail_closed.py::test_missing_client_denied_401`,
`::test_malformed_client_denied_401`, `::test_unauth_merchant_get_denied_401`.
`tests/test_get_deny_by_default.py` (5 tests).
`tests/test_api_key_auth_bypass.py` (6 tests — the dev bypass cannot fire in production).
`tests/test_approval_gate.py` (13 tests, including
`::test_every_merchant_route_carries_the_approval_dep`, which is what keeps the gate from
being forgotten on a new route).
`tests/test_merchant_env_isolation.py` (3 tests).
`tests/test_merchant_key_session_mint.py::test_mint_pins_test_env_write_scope_and_org`,
`::test_minted_key_passes_merchant_verify`.
`tests/test_api_keys_org_id.py::test_foreign_org_key_invisible_even_with_same_owner_address`.

⚠ **NOT ENFORCED:** the `rsend_live_` prefix and the 48-hex length; the case-sensitivity of
`Bearer`; the `403 INSUFFICIENT_SCOPE` body.

---

## §6 — Error envelopes

There is more than one shape. **The promise that is worth making is that no new shape
appears** — not that there is only one.

### We promise

These eight structurally distinct bodies are the complete set on the merchant API. We will
not add a ninth.

| # | Body | Produced by |
|---|---|---|
| 1 | `{error, message}` | auth middleware — `app/middleware/api_auth.py:39-62` |
| 2 | `{error, message, max_bytes}` | 413 — `app/middleware/input_sanitization.py:42-49` |
| 3 | `{error, message, detail}` | 500 — `app/middleware/error_handler.py:26-33` |
| 4 | `{error, retry_after}` — **no `message`** | 429 per-endpoint — `app/middleware/rate_limit.py:296-307` |
| 5 | `{error, message}` — **no `retry_after`** | 429 global per-key — `rate_limit.py:409-416` |
| 6 | `{detail: {error, message}}` | route errors; `TESTNET_ONLY` also carries `allowed_chains` |
| 7 | `{detail: {code}}` (+ `reason` when declined) | KYB gate — `app/api/deps/approval_policy.py:50-77` |
| 8 | `{detail: [ {...}, ... ]}` — **an array** | Pydantic 422 |

Note that shapes 6, 7 and 8 all live under `detail`, but `detail` is an **object** in 6 and
7 and an **array** in 8.

A parser that handles all eight:

```php
$d   = $body['detail'] ?? null;
$e   = (is_array($d) && !array_is_list($d)) ? $d : $body;   // guard the 422 array
$code = $e['error'] ?? $e['code'] ?? null;
```

The guard against a list-shaped `detail` is required. The version published on our docs site
omits it.

Error codes on the merchant surface: `INVALID_API_KEY`, `INSUFFICIENT_SCOPE`,
`approval_pending`, `approval_declined`, `UNSUPPORTED_CHAIN`, `UNSUPPORTED_TOKEN`,
`TESTNET_ONLY`, `MAINNET_ONLY`, `INVALID_STATE`, `INVALID_STATUS`, `WEBHOOK_INACTIVE`,
`INTENT_NOT_FOUND`, `WEBHOOK_NOT_FOUND`, `SETTLEMENT_IN_FLIGHT`,
`DUPLICATE_REQUEST_IN_FLIGHT`, `SETTLEMENT_WALLET_MISSING`, `SETTLEMENT_WALLET_AMBIGUOUS`,
`SPLIT_UNAVAILABLE`, `RECIPIENT_CHAIN_MISMATCH`, `AMOUNT_PRECISION_EXCEEDED`,
`DUPLICATE_PENDING_INTENT`,
`WEBHOOK_URL_FORBIDDEN`, `RATE_LIMIT_EXCEEDED`,
`KEY_RATE_LIMIT_EXCEEDED`, `MONTHLY_LIMIT_EXCEEDED`, `RATE_LIMIT_UNAVAILABLE`,
`PAYLOAD_TOO_LARGE`, `SERVICE_OVERLOADED`, `REQUEST_TIMEOUT`, `INTERNAL_ERROR`.

### We do not promise

- **Anything about an edge proxy in front of this API.** If you call through
  `https://pay.rsends.io/api/backend/...`, a Next.js route sits in the middle
  (`apps/web/app/api/backend/[...path]/route.ts`). It introduces a **ninth** shape that
  exists nowhere in the backend — `502 {error: "BACKEND_UNREACHABLE", message}` on its 25 s
  edge timeout (`:120-127`) — and it strips response headers (see §10). The eight shapes
  above are a promise about **the backend**.
- Human-readable `message` strings. Branch on the code; display the message.

### Enforced by

`tests/test_approval_gate.py` (13 tests) for shape 7, including the `reason` field.
`tests/test_merchant_fail_closed.py` (3 tests) for shape 1.
`tests/test_security.py::TestInputSanitization::test_oversized_payload_rejected` for shape 2.
`tests/test_cancel_settlement_hold.py` for `SETTLEMENT_IN_FLIGHT`.
`tests/test_webhook_egress_loopback_escape.py` for `WEBHOOK_URL_FORBIDDEN`.

⚠ **NOT ENFORCED — this is the weakest promise in the document.** There is no
shape-inventory test anywhere. Nothing would fail if a ninth envelope appeared tomorrow.
Individually unenforced: shapes 3, 4, 5, 6 and 8, and the `403 INSUFFICIENT_SCOPE` body.

---

## §7 — Hosted checkout URL

### We promise

The payer URL has the form **`{checkout_host}/pay/{intent_id}`**, with **no locale
prefix**. Nothing redirects or rewrites `/pay/*` today: the i18n middleware matcher
explicitly excludes it (`apps/web/middleware.ts:96-98`) and no `redirects()` entry matches
it (`apps/web/next.config.mjs:58-89`).

**If this path ever moves, the old path will redirect — it will not disappear.**

### We do not promise

- **That a locale prefix works.** `/en/pay/{id}` is a **404**: there is no
  `app/[locale]/pay` route. Never prefix.
- **The display language.** It is negotiated server-side from the payer's `Accept-Language`
  (`apps/web/app/pay/[intentId]/layout.tsx:31-36`). There is no parameter to force it.
- **The host.** That is deployment configuration, not code. Make it configurable in your
  integration. See §12.
- **Any query parameter.** The page reads none — no `return_url`, no `redirect_url`, no
  `callback`. Anything you append is silently ignored.

### Enforced by

⚠ **NOT ENFORCED.** No test resolves this route, no test covers the `/en/pay/{id}` 404, and
there is no middleware test file at all. The only indirect coverage asserts that the
dashboard's copy button *builds* the string
(`apps/web/app/__tests__/app/paymentsCreate.test.tsx:113`).

---

## §8 — Hosted checkout rendering floor

If you open the checkout in a popup or a sized window, you need a size that is safe to use
and safe to keep using.

### We promise

**The hosted checkout stays usable at 500 × 720 CSS pixels, and this floor will not rise.**

The layout itself stays free to change completely — this is a promise about a threshold, not
about a design.

How that number is derived, from the code:

- The widest hard constraint is **ours, and it is in the loading skeleton**: a
  `width={396}` placeholder (`apps/web/app/pay/[intentId]/_components/CheckoutSkeleton.tsx:41`)
  inside a flex **column**, so it never shrinks. Usable card width is
  `min(460, W−40) − 2·clamp(22, 0.05W, 32) − 2`
  (`apps/web/app/pay/_components/payUi.tsx:100, :114, :118`), which clears 396 px only from
  about **W = 487** upward. Below that the bar is clipped, silently, because the body sets
  `overflow-x: hidden` (`apps/web/app/globals.css:38`) — there is no horizontal scrollbar to
  reveal it.
- Real content is far less demanding: the tightest real state needs roughly 330 px.
- For height, the tallest real state — a four-recipient split plus the token-approval step —
  runs about 640–700 px (`_components/CheckoutFrame.tsx:36-65` plus real content). The page
  scrolls vertically when the window is shorter: the shell uses `min-height: 100vh`, and
  nothing on the route is `position: fixed`.

### We do not promise

**The wallet-connection modal's floor, because it is not ours.** RainbowKit 2.2.10 renders
its compact dialog at a hard `min-width: 368px`
(`node_modules/@rainbow-me/rainbowkit/dist/index.css:2083-2086`) with a 318 px WalletConnect
QR (`dist/index.js:4551`), on an overlay that does not scroll. That is roughly 370 × 520 and
it moves with the dependency's version. Our 500 × 720 clears it comfortably today, but we
cannot freeze someone else's CSS.

One consequence worth knowing: RainbowKit picks mobile-vs-desktop by **user agent**, not by
width. A narrow *desktop* popup therefore gets the desktop connect flow inside that 368 px
dialog — the tightest configuration in the product.

### Enforced by

⚠ **NOT ENFORCED.** The only dimensional assertions in the repository are two `minHeight`
checks (`apps/web/app/__tests__/pay/checkoutSkeleton.test.tsx:69-70`). There is no
Playwright, no viewport test, and no overflow test.

---

## §9 — Security properties we will not weaken

### We promise

**The hosted checkout cannot be framed.** `frame-ancestors 'none'` in the CSP **and**
`X-Frame-Options: DENY`, both applied to every route (`apps/web/next.config.mjs:115, :119`).
An `<iframe>` integration has never been possible and will not become possible. **A popup or
a full redirect is the only integration shape**, and we will not take that away.

Also held: `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, `object-src 'none'`,
`base-uri 'self'`, `form-action 'self'` (`next.config.mjs:118-122`).

**On the API side:** the public payer view stays id-as-secret — a 128-bit CSPRNG id, a
single-object lookup with no list or filter route, an explicit 8-field allowlist
(`status`, `amount`, `currency`, `chain`, `expires_at`, `merchant_name`, `tx_hash`,
`onchain`), read-only, `404` on miss (`app/api/public_routes.py:35-113`). Rate limiting is
**fail-closed**: if Redis is unavailable the API returns `503 RATE_LIMIT_UNAVAILABLE` rather
than letting traffic through.

### We do not promise

- **HSTS on the checkout origin.** The app does not set it. The only
  `Strict-Transport-Security` in this repository is the nginx config in front of the backend
  API host (`services/backend/nginx/nginx.conf:43`). On the checkout origin it would be
  platform-provided, so it is not ours to promise.
- **CORS access.** In production the allowed-origin list is empty. You cannot call
  `/api/pay/*` from a browser on your own domain — open the page instead.

### Enforced by

API side: `tests/test_public_intent_view.py` — `::test_public_view_leaks_nothing` (asserts
the exact 8-key allowlist), `::test_no_list_or_enumeration_route`,
`::test_expired_pending_reported_not_persisted`, `::test_unknown_id_404`,
`::test_public_view_per_ip_rate_limited`, `::test_merchant_get_no_longer_public`.

⚠ **NOT ENFORCED:** every header promise in this section. A grep for
`Content-Security-Policy` or `X-Frame-Options` across all test directories returns **zero
hits**. The strongest promise in this document is the least defended one.

---

## §10 — Rate limits and idempotency

### We promise

**We will not lower an existing limit without notice.** These are floors, not frozen values;
raising them is always fine.

| Endpoint | Limit | Keyed by |
|---|---|---|
| `POST /payment-intent` | 100 / 60 s | API key |
| `POST /payment-intent/{id}/cancel`, `/resolve` | 10 / 60 s | API key |
| `GET /payment-intent/{id}` | 60 / 60 s | API key |
| `GET /transactions` | 60 / 60 s | API key |
| `POST /webhook/register` | 5 / hour | API key |
| `POST /webhook/test` | 10 / 60 s | API key |
| `GET /public/payment-intent/{id}` | 20 / 60 s | **IP** |
| Global, all endpoints | 100 / minute | API key |

Source: `app/middleware/rate_limit.py:50-101`, `:388-416`.

**Idempotency.** The header is **`X-Idempotency-Key`** (not `Idempotency-Key`), it applies to
`POST` and `PUT`, the TTL is 24 hours, and **only 2xx responses are replayed**
(`app/middleware/idempotency.py:34, :44, :120`). A concurrent duplicate that arrives while
the first is still in flight gets `409 DUPLICATE_REQUEST_IN_FLIGHT`.

### We do not promise

- **`Retry-After` on every 429.** It is present on the per-endpoint 429
  (`rate_limit.py:296-307`) and **absent** on the global per-key 429 (`:409-416`) and on
  `MONTHLY_LIMIT_EXCEEDED`. Back off on your own schedule if the header is missing.
- **Any response header at all, if you call through the documented edge URL.** The Next.js
  proxy re-emits **only `Content-Type`** (`apps/web/app/api/backend/[...path]/route.ts:115-118`).
  `Retry-After`, `X-RateLimit-*`, `X-Request-ID` and `X-Correlation-ID` do not survive it. It
  also allowlists **request** headers (`:33-46`) — anything outside
  `content-type, accept, x-wallet-*, x-timestamp, x-idempotency-key, x-chain-id,
  authorization` is dropped before it reaches the backend.
- **Cross-merchant idempotency isolation.** The cache key is
  `sha256(path + ":" + your_key)` (`idempotency.py:56`) with no merchant, environment,
  method, or body in it. This is why globally-unique keys are an obligation and not a
  suggestion. See "Your half of the contract", item 2.
- **Idempotency during a Redis outage.** Rate limiting is fail-**closed** (503). Idempotency
  on merchant paths is fail-**open** — the request executes unprotected
  (`idempotency.py:58-68`).

### Enforced by

`tests/test_rate_limit_matching.py::test_create_intent_uses_create_limit`,
`::test_cancel_uses_stricter_subpath_limit`, `::test_resolve_uses_stricter_subpath_limit`,
`::test_get_intent_by_id_uses_get_subpath_limit`.
`tests/test_public_intent_view.py::test_public_view_per_ip_rate_limited`.

⚠ **NOT ENFORCED:** **the idempotency middleware has zero test coverage** — not the header
name, not the cache key, not the TTL, not the 2xx-only replay, not the 409, not the
fail-open. Also unenforced: the `/transactions` and webhook-route limits; `Retry-After` on
any response; the fail-closed 503 at runtime.

---

## §11 — Versioning policy

**None of the mechanism below exists yet.** A grep for `Deprecation`, `Sunset` or
`X-API-Version` across the backend returns nothing, and the only version signal on the wire
is the `v1` path segment. The OpenAPI schema is not served in production
(`app/main.py:229-233`), so a generated client cannot be validated against the live API. This
section is a commitment about how we will behave, not a description of what ships today.

### What is not a breaking change

These may ship in any release, without notice, and your client must tolerate them:

- a new key in a webhook payload;
- a new optional field in a response;
- a new value in any enumeration — status, event name, or error code;
- a new optional request field;
- a raised rate limit;
- any change to the hosted checkout's visual design, above the §8 floor.

### What is a breaking change

Removing or renaming a field, a key, an enumerated value, or an error code. Making an
optional request field required. Changing a field's type. Lowering a rate limit. Changing
the signature scheme, the signed-string construction, or a header name. Raising the §8
rendering floor. Removing the `/pay/{intent_id}` path shape without a redirect.

### How one ships

1. **A new path prefix.** `/api/v2/...`, alongside `/api/v1/...`. We do not mutate a
   version in place.
2. **The old version keeps working** for the whole announced window — not degraded, not
   rate-limited differently.
3. **Announcement before the window opens**, with a stated minimum notice period, through
   the channels in the next section.
4. **`Deprecation` and `Sunset` response headers** on the outgoing version, per RFC 8594, so
   an integration can surface the warning to its own operator without anyone reading an
   email.
5. **The webhook payload is versioned with the event, not the path.** A breaking payload
   change ships as a new event name, and the old event keeps firing for the window.

### Prerequisites we do not have yet

- **The edge proxy strips headers in both directions** (§10). Until
  `apps/web/app/api/backend/[...path]/route.ts` forwards a client version header and
  propagates `Deprecation`/`Sunset`, steps 3 and 4 above reach nobody.
- **We cannot see who is out there.** Nothing records an integration's identity or version;
  `User-Agent` is captured into a context variable on the merchant surface and read by
  nothing. Until integrations declare themselves, "announcement" means a blog post and hope.

Both are tracked as work, not as promises.

---

## §12 — Open questions — deliberately not promised

Things that are not verifiable in this repository, and therefore are not commitments:

1. **The hosted checkout host.** The docs site says `demo.rsends.io/pay/{id}`; the API base
   in the same docs is `pay.rsends.io/api/backend`. Which is canonical is a deployment fact.
   Make the host configurable.
2. **Confirmation latency.** `INDEXER_USE_FINALIZED_TAG` defaults to `True`
   (`services/backend/app/config.py:99`), which is roughly 13 minutes on Base, but the
   environment can set a block depth instead (~35 seconds). The live value is not in the
   repository. Do not put a number in your user-facing copy.
3. **Whether HSTS is applied to the checkout origin by the hosting platform** (§9).

---

## Changing this document

If code and this document diverge, **the code is the source of truth** — but the divergence
is a defect in one of them, and the same review must fix it. Adding a promise means adding
or citing the test that holds it. Removing one means saying so in the changelog below.

| Date | Change |
|---|---|
| 2026-08-12 | v1. Initial contract, verified against `main` @ `6c79e8d9`. |
