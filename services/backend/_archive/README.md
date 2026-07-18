# _archive — dead backend code kept for reference

Mirror of the `apps/web/_archive/` convention: code removed from the live app but kept
in-tree for its reference value. Nothing in here is imported by `app/` or collected by
pytest.

- `webhook_verifier.py` (archived 2026-07-18) — inbound Alchemy-webhook verifier
  (HMAC / IP allowlist / freshness / Redis idempotency). Written but never wired: zero
  importers, and no route ever registered `POST /api/v1/webhooks/alchemy`. Payment
  detection is (and was) the on-chain PaymentMade polling indexer. Kept because the
  verification logic would be a useful starting point if an inbound webhook is ever
  actually built (deliberately skipped in the 2026-07-18 discovery: the durable-cursor
  indexer cannot miss events, so a same-vendor webhook adds no safety).
- `verify_celery_fix.py`, `stress_webhook_flood.py` (archived 2026-07-18) — dev/stress
  scripts whose sole target was the phantom `POST /api/v1/webhooks/alchemy` (a 404).
