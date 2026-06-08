# RPagos Command Center — Deploy Checklist

## Frontend (Vercel / Next) — Environment Variables

- [ ] **M11** — `ADMIN_TOTP_SECRET` (base32) **set before go-live**. In production (`NODE_ENV=production`) an empty value makes admin login return **HTTP 503** (fail-closed — no password-only bootstrap). Generate out-of-band, set on Vercel, redeploy. Does NOT affect the backend.
- [ ] `ADMIN_SECRET` — admin password (`openssl rand -hex 32`)
- [ ] `ORACLE_SIGNER_MODE=remote` — Next delegates EIP-712 signing to the backend (which itself must be `kms`); keeps the oracle key out of the web tier.
- [ ] `INTERNAL_PROXY_SECRET` — must match the backend value (else internal calls are rejected).
- [ ] `HMAC_SECRET` — must match the backend value.

## Secrets & Environment Variables (Render)

- [ ] `ALCHEMY_WEBHOOK_SECRET` — set on Render
- [ ] `SWEEP_PRIVATE_KEY` — migrate to AWS KMS (NOT in .env)
- [ ] `TELEGRAM_BOT_TOKEN` — set on Render
- [ ] `SENTRY_DSN` — set for error tracking
- [ ] `DATABASE_URL` — PostgreSQL connection string
- [ ] `REDIS_URL` — Redis connection string

## Alchemy Webhook Setup

- [ ] Create Alchemy Webhook (Address Activity) → point to `https://<backend-url>/api/v1/webhooks/alchemy`
- [ ] Add all monitored `source_wallet` addresses to webhook filter
- [ ] Verify webhook fires on test TX (Base Sepolia)

## Telegram Bot

- [ ] Create bot via @BotFather
- [ ] Get `chat_id` for notification target
- [ ] Test with `GET /api/v1/health/sweep` after config

## Connectivity

- [ ] Verify WebSocket connection from Vercel frontend to Railway backend (`wss://<backend>/ws/sweep-feed/{owner}`)
- [ ] Configure CORS for WebSocket on Railway (check `cors_origins` setting)
- [ ] Test end-to-end: create rule → trigger webhook → receive WS event

## Monitoring

- [ ] Prometheus metrics exposed at `/metrics`
- [ ] Dashboard Grafana for sweep monitoring (`sweep_total`, `sweep_latency_seconds`, `sweep_gas_gwei`)
- [ ] Alert: sweep failure rate > 10% over 5m window
- [ ] Alert: no successful sweep in 1h (when active rules exist)
- [ ] Sentry error tracking verified

## Security & Performance

- [ ] Rate limit review for sweep endpoints (current: `RateLimitMiddleware`)
- [ ] Backup strategy for `sweep_logs` table (pg_dump cron or managed backup)
- [ ] Private key rotation plan documented
- [ ] HTTPS enforced on all endpoints
