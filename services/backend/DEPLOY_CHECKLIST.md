# RSends Backend — Deploy Checklist

Production deployment procedure for rpagos-backend.
Run through every section in order. Do not skip steps.

---

## 1. Pre-Deploy Security Audit

- [ ] **Secrets rotated**: `HMAC_SECRET`, DB password
- [ ] **No secrets in code**: `grep -r "password\|secret\|private_key" app/ --include="*.py"` returns only config references
- [ ] **`.env` not in repo**: `git ls-files .env` returns empty
- [ ] **CORS origins**: `cors_origins` in `.env` set to production domains only (no `localhost`)
- [ ] **Debug mode OFF**: `DEBUG=false` in `.env`
- [ ] **Swagger hidden**: `docs_url=None` in production (auto when `debug=False`)
- [ ] **Rate limits configured**: verify `RateLimitMiddleware` is active
- [ ] **Telegram bot token**: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- [ ] **Sentry DSN**: set `SENTRY_DSN` for error tracking
- [ ] **KMS signer** (if applicable): `SIGNER_MODE=kms`, `KMS_KEY_ID` set, IAM role attached

### Fail-closed startup gates (backend will NOT boot in prod if unset)

These are validated by `validate_settings()` — with `DEBUG=false` the process **exits at startup** (StartupValidationError) until set:

- [ ] **H4** — `WALLET_AUTH_ALLOW_LEGACY=false` (default `true` is rejected in prod; legacy wallet sigs are replayable). Flip BEFORE promoting this build.
- [ ] **M1-A** — `ORACLE_SIGNER_MODE=kms` **and** `ORACLE_KMS_KEY_ID` (or `ORACLE_KMS_KEY_IDS` for multisig). Any non-`kms` value (`local`/`remote`) is rejected in prod — it would sign with a local key in the web tier.

> Note: `ADMIN_TOTP_SECRET` is a **frontend (Vercel)** var, not a backend one — see the frontend deploy checklist. It does not affect backend startup.

---

## 2. Environment Variables

Verify all required vars are set in the production `.env`:

```bash
# Required
DATABASE_URL=postgresql+asyncpg://rpagos:<password>@<host>:5432/rpagos
REDIS_URL=redis://<host>:6379/0
HMAC_SECRET=<min-32-chars>
SWEEP_PRIVATE_KEY=<hot-wallet-key>   # or use KMS

# Alchemy
ALCHEMY_API_KEY=<key>

# Telegram Notifications
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<chat_id>

# Celery
CELERY_BROKER_URL=redis://<host>:6379/1
CELERY_RESULT_BACKEND=redis://<host>:6379/2

# Monitoring
SENTRY_DSN=https://<key>@sentry.io/<project>

# Compliance
DAC8_REPORTING_ENTITY_NAME=<entity>
DAC8_REPORTING_ENTITY_TIN=<tin>
DAC8_REPORTING_COUNTRY=<country_code>

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
CORS_ORIGINS=https://rsends.io,https://www.rsends.io

# Fail-closed startup gates (prod: backend exits if unset/wrong)
WALLET_AUTH_ALLOW_LEGACY=false           # H4 — must be false in prod
ORACLE_SIGNER_MODE=kms                    # M1-A — only 'kms' allowed in prod
ORACLE_KMS_KEY_ID=<oracle-kms-key>        # or ORACLE_KMS_KEY_IDS=<k1,k2,k3> (multisig)
```

---

## 3. Database Migration

> **On Render (production): migrations run as a Pre-Deploy Command, not at boot.**
> Set Pre-Deploy Command = `alembic upgrade head` and env `RUN_MIGRATIONS_ON_BOOT=0` (see [MIGRATIONS.md](./MIGRATIONS.md)).
> A failed pre-deploy migration aborts the deploy (old version keeps serving) — this is intended.
> Every migration MUST be backward-compatible with the previous release — follow the Expand/Contract rule in [MIGRATIONS.md](./MIGRATIONS.md).

The block below is the **manual / free-tier fallback** procedure (run from the Render Shell
before promoting a schema-changing release):

```bash
# 1. Backup current database
pg_dump -h <host> -U rpagos -d rpagos > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Check current migration state
alembic current

# 3. Run pending migrations
alembic upgrade head

# 4. Verify no drift (autogenerate should produce empty migration)
alembic revision --autogenerate -m "check_drift"
# Inspect the generated file — upgrade() and downgrade() should be empty
# Delete the generated file after verification

# 5. Verify tables exist
psql -h <host> -U rpagos -d rpagos -c "\dt"
```

---

## 4. Contract / Wallet Deploy

- [ ] **Hot wallet funded**: minimum 0.1 ETH on Base (chain 8453)
- [ ] **Nonce synced**: wallet nonce matches on-chain nonce
- [ ] **Test transaction**: send 0.0001 ETH to a test address, verify via `/health/sweep`
- [ ] **Indexer detecting**: on-chain PaymentMade polling is the ONLY tx-detection path
      (no inbound webhook exists) — check startup log `tx_detection=polling` and `/health`

```bash
# Verify hot wallet balance
curl -s https://<domain>/health/sweep | jq '.checks.hot_wallet'

# Verify nonce
curl -s https://<domain>/health/sweep | jq '.checks'
```

---

## 5. Monitoring Setup

### Prometheus + Alertmanager

- [ ] **Prometheus scraping**: `curl http://prometheus:9090/api/v1/targets` shows `rpagos-api` as UP
- [ ] **Alert rules loaded**: `curl http://prometheus:9090/api/v1/rules` shows all rule groups
- [ ] **Alertmanager reachable**: `curl http://alertmanager:9093/-/ready`
- [ ] **Alert receivers configured**: Telegram/Slack/PagerDuty in `alertmanager.yml`

### Grafana

- [ ] **Dashboards imported**: sweep pipeline, circuit breakers, hot wallet, queue depth
- [ ] **Data source configured**: Prometheus URL in Grafana data sources

### Verification

```bash
# Check metrics endpoint
curl -s https://<domain>/metrics | head -20

# Check all health endpoints
curl -s https://<domain>/health
curl -s https://<domain>/health/ready
curl -s https://<domain>/health/sweep
curl -s https://<domain>/health/dependencies
curl -s https://<domain>/health/deep
```

---

## 6. Service Startup Order

```bash
# 1. Infrastructure
docker compose up -d postgres redis

# 2. Run migrations
docker compose run --rm api alembic upgrade head

# 3. Start API
docker compose up -d api

# 4. Start Celery workers
docker compose up -d worker

# 5. Start Celery beat
docker compose up -d beat

# 6. Start monitoring stack
docker compose up -d prometheus grafana alertmanager

# 7. Start reverse proxy
docker compose up -d nginx

# 8. Verify everything
docker compose ps     # all containers should be "Up"
curl -s https://<domain>/health/sweep | jq '.status'
# Should return "healthy"
```

---

## 7. Rollback Procedure

### API Rollback

```bash
# 1. Stop current API
docker compose stop api worker beat

# 2. Revert to previous image
docker compose pull api  # if using registry tags
# OR: docker tag rpagos-api:previous rpagos-api:latest

# 3. Rollback database (if migration was applied)
alembic downgrade -1

# 4. Restart with previous version
docker compose up -d api worker beat

# 5. Verify health
curl -s https://<domain>/health/sweep | jq '.status'
```

### Emergency: Full Rollback

```bash
# Stop everything
docker compose down

# Restore database from backup
psql -h <host> -U rpagos -d rpagos < backup_<timestamp>.sql

# Start previous version
git checkout <previous-tag>
docker compose up -d --build
```

---

## 8. Gradual Capacity Increase Schedule

After initial deploy, increase capacity gradually over 7 days:

| Day | Max Rules | Daily Vol Cap | Spending/Hour | Notes |
|-----|-----------|---------------|---------------|-------|
| 0   | 5         | 0.5 ETH       | 0.1 ETH       | Deploy day — smoke test only |
| 1   | 10        | 1.0 ETH       | 0.2 ETH       | Monitor circuit breakers |
| 2   | 25        | 2.5 ETH       | 0.5 ETH       | Check daily digest |
| 3   | 50        | 5.0 ETH       | 1.0 ETH       | Review alert thresholds |
| 5   | 100       | 10.0 ETH      | 2.0 ETH       | Full monitoring validated |
| 7   | Unlimited | 50.0 ETH      | 10.0 ETH      | Production limits |

Update spending limits via:
```bash
# Example: update hourly limit
curl -X PUT https://<domain>/api/v1/forwarding/spending-limits \
  -H "Content-Type: application/json" \
  -d '{"per_hour_eth": 0.2, "per_day_eth": 1.0, "global_daily_eth": 1.0}'
```

---

## 9. Post-Deploy Verification

Run within 30 minutes of deploy:

- [ ] **Health check passes**: `curl /health/sweep` returns `"healthy"`
- [ ] **DB connected**: `/health/ready` checks.db = `"ok"`
- [ ] **Redis connected**: `/health/ready` checks.redis = `"ok"`
- [ ] **Celery workers alive**: `/health/sweep` checks.celery.workers > 0
- [ ] **Circuit breakers closed**: no OPEN breakers in `/health/sweep`
- [ ] **Metrics flowing**: `curl /metrics` returns `rsend_*` metrics
- [ ] **Telegram test**: trigger a test notification, verify delivery
- [ ] **WebSocket test**: open Command Center, verify real-time feed
- [ ] **Sweep test**: create a forwarding rule, send small TX, verify sweep completes
- [ ] **Daily digest**: check next morning for digest message

---

## 10. Ongoing Maintenance

- **Weekly**: review Grafana dashboards for anomalies
- **Monthly**: rotate `HMAC_SECRET`
- **Quarterly**: audit forwarding rules, review spending limits
- **On incident**: update alert thresholds based on learnings
