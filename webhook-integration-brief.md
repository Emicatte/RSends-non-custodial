# Webhook integration brief — what is true on main, 2026-07-29

Read-only extraction from the codebase. Every claim carries a file:line. "Backend" = `services/backend`.

## 1. Signature

**Say:** "Every delivery carries `X-RSend-Signature`: hex HMAC-SHA256 over the string `"{timestamp}.{raw body}"`, keyed with a per-endpoint secret. The timestamp travels in `X-RSend-Timestamp` (unix seconds), and our reference verifier enforces a 5-minute freshness window for replay protection. Stripe-style."

- Headers + composition: `app/services/webhook_service.py:242-244` (header names), `:247-265` (`compute_webhook_signature`: `timestamp.encode() + b"." + payload_bytes`, HMAC-SHA256 hex).
- Signing at send time, over the exact bytes POSTed: `webhook_service.py:1185-1199` (real deliveries), `:1312-1321` (test event — same scheme).
- Replay window: 300 s tolerance in the reference verifier `verify_webhook_signature` (`webhook_service.py:244`, `:268-304`) — constant-time compare. Note honestly: the window is enforced **by the merchant's verification**, not by us; we just recompute the timestamp per attempt (`webhook_service.py:1186-1188`) so retried deliveries stay verifiable.
- Secret: 64-hex-char CSPRNG generated at registration (`webhook_service.py:184`), returned **once** in the register response — API-key route `app/api/merchant_routes.py:254` + `:300`, session route `app/api/user_org_webhooks_routes.py:174`. Delivery-log and list responses never include it (`user_org_webhooks_routes.py:15`).
- **Rotation: not implemented.** No rotate/delete/deactivate endpoint exists (route inventory: `merchant_routes.py` has only register/test; `user_org_webhooks_routes.py` has list/deliveries/register/test). Rotation today = register a new endpoint; the old one cannot even be disabled via API.
- The skipped "HMAC" test (`tests/test_security.py:145`) is about a **different, inbound** scheme (`hmac_service`, tx-callback field-based signing) — it pinned a removed debug backdoor (placeholder acceptance) and is correctly dead. It is not a superseded version of the webhook scheme above.

## 2. Retry behaviour

**Say:** "Five total attempts, exponential backoff base-4, 10-second HTTP timeout each. 2xx is success; any non-2xx, timeout or connection error retries — we don't distinguish 4xx from 5xx. After the fifth failure the delivery is marked failed and stays queryable in the delivery log."

- MAX_RETRIES=5, timeout 10 s: `webhook_service.py:56-58`. Success = `200 <= status < 300` (`:1213`), everything else retries (`:1222-1243`), permanent fail at 5 (`:1248-1254`).
- **Doc-vs-code disagreement:** the comment advertises 30s, 2m, 8m, 32m, 2h (`webhook_service.py:21`, `:57`) but the code computes backoff **after** incrementing (`:1257`), so real gaps are **2m, 8m, 32m, ~2h8m** — the 30 s slot never happens. Total window ≈ 2h50m.
- First attempt is immediate and inline for indexer/expiry events (`send_webhook`, `webhook_service.py:1438`); the retry queue is drained every 15 s by Celery beat or an asyncio fallback loop started at app startup (`app/tasks/webhook_tasks.py:38-62`, `:175-189`; wiring `app/main.py:159-174`).
- Permanent failure without retry: URL fails the SSRF egress re-check before an attempt (`webhook_service.py:1174-1183`), or the webhook row is inactive/missing (`:1151-1153`).
- After the final attempt: row status `failed`, an ERROR log line (`:1250`) — **no operator alert, no dead-letter processing, no replay endpoint** (merchant- or operator-side). One nuance worth knowing: if the *dispatch itself* fails at the indexer (before a delivery row exists), an atomic claim is released and re-attempted every tick until it succeeds (`app/services/payment_indexer.py:899-966`) — but a delivery that exhausted its 5 HTTP attempts is dead.
- Delivery log: yes, merchant-visible. `GET /api/v1/user/org/webhooks/{id}/deliveries` (session dashboard, paginated, tenant-scoped 404) returns event type, status, response code, retries, timestamps — deliberately **excluding** payload and response body (`user_org_webhooks_routes.py:113-171`). No API-key equivalent.

## 3. Idempotency

**Say:** "Every payload carries a stable `event_id` (`evt_` + UUID) that never changes across retries, and every delivery carries `X-RSend-Delivery-Id`, a stable key of intent + event type + endpoint. Dedupe on either. Delivery is at-least-once, so dedupe is mandatory."

- `event_id` assigned once in the single payload builder (`webhook_service.py:1077-1080`); the payload is persisted on the delivery row at creation (`:1424-1433`) and each retry serializes that stored payload (`:1185`), so `event_id` is identical across retries.
- Headers: `X-RSend-Delivery-Id` = idempotency key `{intent_id}:{event}:{webhook_id}`, stable; `X-RSend-Delivery` = fresh UUID **per attempt** (`webhook_service.py:1191-1200`). The docs tell merchants to dedupe on `X-RSend-Delivery-Id` (`apps/web/app/docs/webhooks/page.tsx:142`, `:177`).
- Duplicate suppression on our side: DB dedup on the idempotency key inside the same transaction as the row (`webhook_service.py:1410-1419`), plus atomic single-winner claims at the indexer (`webhook_fired_at` NULL→now, `payment_indexer.py:910-932`; mirror `reversal_fired_at` for reversals `:1007-1021`). Duplicate on-chain logs are idempotent (pinned: `tests/test_payment_indexer_reorg.py:261` `test_duplicate_log_is_idempotent`).
- Can the same logical event arrive twice? The same *delivery* can (at-least-once HTTP). A *second* `payment.completed` for the same intent+endpoint cannot — even if a reversed tx is later re-included, no second completed fires; it's logged for manual reconciliation instead (`payment_indexer.py:918-931`). One real sequence to warn them about: `payment.completed` → `payment.reversed` on a deep reorg (documented, `page.tsx:62-67`).

## 4. Underpayment

**Say:** "On the live on-chain path, an underpaid transfer is recorded as a **rejected settlement**: no webhook fires, the intent stays pending and the invoice remains payable. The payer simply hasn't paid yet, by design — a stranger must not be able to flip someone's invoice with a 1-wei payment."

- Validator: on-chain amount must be `>= ` invoice amount in base units (`payment_indexer.py:459-489`, amount check at `:486-487`); mismatch → settlement `rejected`, alert log, **no webhook, intent untouched** (`payment_indexer.py:784-795`).
- Pinned by `tests/test_payment_indexer_reorg.py:283` `test_validation_mismatch_rejected_not_paid`, parametrized with `("amount", AMT - 1, …)` (`:279`); assertions: `assert s.status == SettlementStatus.rejected` (`:297`), `assert (await _intent(iid)).status == IntentStatus.pending` (`:300`), `assert webhook_calls == []` (`:307`). Split variant: `tests/test_indexer_split.py:329` `test_underpaid_split_total_rejected`.
- **Disagreement to disclose if pressed:** a legacy matching path (`finalize_match`, `webhook_service.py:876-953`) implements partial/overpaid states and a `payment.partial` webhook — but it has **zero callers** in `app/` today. `payment.partial` cannot actually be emitted. Overpayment on the live path passes validation (only `<` fails) and arrives as a normal `payment.completed`.

## Event types — emitted today vs. defined

**Actually emittable on main:**

| Event | Trigger | Site |
|---|---|---|
| `payment.completed` | Settlement observed on-chain, validated, finalized; single-winner claim | `payment_indexer.py:899-954` |
| `payment.reversed` | Chain reorg un-finalizes a settlement whose `completed` already fired | `payment_indexer.py:1007-1036` |
| `payment.expired` | Expiry sweep (60 s), atomic pending→expired claim, settlement-hold aware | `app/tasks/webhook_tasks.py:111-155` |
| `test` | Merchant-triggered test fire | `webhook_service.py:1294-1340` |
| `payment.completed_late` | Only via merchant resolving an intent already in `review` (`POST /payment-intent/{id}/resolve`) | `merchant_routes.py:452-457` |

**Defined in the contract but with no live trigger:** `payment.partial`, `payment.overpaid`, `payment.needs_review`, `payment.expired_rejected` all originate in the caller-less legacy matching path (`review` status is only ever written there: `webhook_service.py:377,913-926`). `payment.cancelled` / `payment.ambiguous` are honestly documented as "Reserved — not yet emitted" (`page.tsx:79`); cancel routes emit nothing. Contract shapes for all of these are still pinned by `tests/test_webhook_contract.py:71-117`.

## Test event

**Say — this one is true and a genuine selling point:** "The test event is built by the exact same payload builder as production, fed a synthetic intent — same key set, same signature scheme. What your handler sees from the test button is byte-shape-identical to a real event."

- `_build_test_event_payload` → `_build_payload("test", synthetic_intent)` (`webhook_service.py:1271-1291`); `_build_payload` is the single builder for every outbound event (`:1056-1072`). Triggered by `POST /api/v1/merchant/webhook/test` (API key) or `POST /api/v1/user/org/webhooks/{id}/test` (dashboard, 10/min). The synthetic intent never touches the DB.

## Sandbox / trying the integration

- Real `rsend_test_` API keys, mintable from the dashboard (`/app` → API keys, admin role, 5-active cap, plaintext shown once): `app/api/user_org_merchant_keys_routes.py`. Test keys act only on testnet (Base Sepolia) data; environment is stamped on intents **and** webhooks, and outbound dispatch filters by it — a test endpoint can never receive a live event (`webhook_service.py:1388-1391`). The dashboard is currently test-env-only, which is honest: mainnet routers aren't cut over yet.

## Honest gaps (say "not yet" before they ask)

1. **No SDKs** — integration is raw HTTP + the Node.js verify snippet in the docs (`page.tsx:151-171`).
2. **No public OpenAPI spec** — Swagger/`openapi.json` are disabled in production (`app/main.py:229-233`); nothing is published.
3. **No replay/redelivery** — a delivery that exhausts 5 attempts is dead; no merchant or operator endpoint re-fires it, and no alert fires on permanent failure.
4. **No secret rotation, no webhook delete/disable via API** — register and test are the only mutations on the webhook resource.
5. **No 4xx/5xx distinction or `Retry-After` handling** — a permanent 404 burns all 5 attempts like a transient 503.
6. **Backoff docs vs. code** — advertised first retry at 30 s, actual first retry at 2 minutes (see §2).
7. **Delivery log lacks the payload** (by design, PII/secret avoidance) and is dashboard-session-only — not reachable with an API key.
8. **Event catalogue is partly aspirational** — docs page exists and is good (`apps/web/app/docs/webhooks/page.tsx`: header table, signed-string spec, verify example, reorg semantics), but `partial`/`overpaid`/`needs_review`/`expired_rejected` are listed without noting they currently have no live trigger.
9. **Delivery is at-least-once** — a crash between a successful POST and the DB write can redeliver; dedupe on `X-RSend-Delivery-Id` is mandatory, and the docs say so.
