# RPagos Backend Core — Identity, Compliance, Data Engine & Merchant B2B API

Python/FastAPI backend for RSend: transaction processing, auto-forwarding, cross-chain execution, AML screening, signing protection, double-entry ledger, DAC8 compliance, multi-auth identity (email/password + Google + GitHub + SIWE wallet), organizations/multi-tenancy, and the merchant B2B billing suite (payment intents, webhooks, billing profile, commission invoices).

## Stack

| Component | Technology | Purpose |
|---|---|---|
| Framework | FastAPI + Uvicorn | Async API server (4 workers prod) |
| Validation | Pydantic v2 | Schema validation |
| Database | SQLAlchemy 2.0 + asyncpg | Async ORM + PostgreSQL (SQLite in tests) |
| Migrations | Alembic | 41 versioned migrations (0000–0040) |
| Cache | Redis + hiredis | Rate limiting, idempotency, nonce dedup, sessions |
| Task Queue | Celery | Async background tasks |
| Identity | PyJWT (HS256) + bcrypt | Access/refresh tokens, password hashing |
| Signing | eth-account + boto3 (KMS) | Local key / AWS KMS / Vault |
| Email | Resend API | Verification + password-reset emails |
| Monitoring | Prometheus + Sentry + OpenTelemetry | Metrics, errors, tracing |
| Anomaly | SciPy + Pandas | Statistical z-score detection |
| Compliance | lxml | DAC8/CARF XML reports |
| Alerts | httpx | Telegram bot + webhook notifications |
| Tests | pytest + httpx + aiosqlite | Async end-to-end tests |

## Architecture

```
rpagos-backend/
├── app/
│   ├── main.py                    # FastAPI app + lifespan + ~30 routers + health checks
│   ├── config.py                  # Pydantic Settings (.env), prod safety asserts
│   ├── celery_app.py              # Celery config + correlation propagation
│   │
│   ├── api/
│   │   ├── routes.py                  # TX callback, anomalies, DAC8
│   │   ├── merchant_routes.py         # B2B merchant API (payment intents, webhooks)
│   │   ├── merchant_profile_routes.py # B2B billing profile (anagrafica, Step 1)
│   │   ├── merchant_invoice_routes.py # Commission invoices (Step 3)
│   │   ├── sweeper_routes.py          # Sweep operations + Alchemy webhooks
│   │   ├── distribution_routes.py     # Batch distribution
│   │   ├── execution_routes.py        # Cross-chain engine
│   │   ├── strategy_routes.py         # Conditional automation DSL
│   │   ├── split_routes.py            # Multi-wallet split contracts
│   │   ├── signing_routes.py          # Signing guard + audit (internal)
│   │   ├── oracle_signer_routes.py    # Internal oracle sign-digest (KMS/local)
│   │   ├── ratelimit_routes.py        # Internal rate-limit check
│   │   ├── aml_routes.py              # AML check + admin panel
│   │   ├── health_routes.py          # /health/deep (5-component)
│   │   ├── ledger_routes.py          # Double-entry ledger + CSV export
│   │   ├── audit_routes.py           # Audit trail + admin auth
│   │   ├── price_routes.py           # Token prices
│   │   ├── dashboard_routes.py       # Aggregated dashboard stats
│   │   ├── websocket_routes.py       # Real-time sweep feed
│   │   ├── payment_ws.py             # Per-intent payment status WS
│   │   ├── api_key_routes.py         # Merchant API keys (/api/v1/keys)
│   │   │
│   │   ├── auth_routes.py             # Session refresh, logout, /me
│   │   ├── auth_email_routes.py       # Email+password signup/login/verify/reset
│   │   ├── wallet_session_routes.py   # SIWE wallet-session login
│   │   ├── account_settings_routes.py # Link/unlink Google/GitHub, add/remove password
│   │   ├── user_account_routes.py     # Sessions, known devices, GDPR delete
│   │   ├── user_routes.py             # Saved routing configs
│   │   ├── user_tx_routes.py          # Persistent tx history + bulk import
│   │   ├── user_contacts_routes.py    # Server-side address book
│   │   ├── user_wallets_routes.py     # SIWE-verified linked wallets
│   │   ├── user_api_keys_routes.py    # User/org-scoped API keys + scopes
│   │   ├── notification_routes.py     # Notification preferences
│   │   ├── organizations_routes.py    # Orgs, members, roles, invites, switch
│   │   └── org_invites_public_routes.py # Public invite preview/accept/decline
│   │
│   ├── models/
│   │   ├── db_models.py           # TransactionLog, ComplianceSnapshot
│   │   ├── forwarding_models.py   # ForwardingRule (versioned), SweepLog
│   │   ├── ledger_models.py       # Account, LedgerEntry (double-entry)
│   │   ├── command_models.py      # DistributionList, SweepBatch
│   │   ├── split_models.py        # SplitContract, SplitExecution
│   │   ├── strategy_models.py     # Strategy (conditions + actions)
│   │   ├── merchant_models.py     # PaymentIntent, MerchantWebhook, WebhookDelivery
│   │   ├── merchant_profile_models.py # MerchantProfile (billing_* anagrafica)
│   │   ├── invoice_models.py      # Invoice + InvoiceCounter (commission billing)
│   │   ├── aml_models.py          # SanctionEntry, AMLAlert, AMLConfig
│   │   ├── signing_models.py      # SigningAuditLog (immutable)
│   │   ├── kms_models.py          # KMSAuditLog (immutable)
│   │   ├── api_key_models.py      # Merchant APIKey (bcrypt v2, scopes, usage)
│   │   ├── auth_models.py         # User, UserSession, AuthAuditLog
│   │   ├── email_auth_models.py   # Email verification + password-reset tokens
│   │   ├── org_models.py          # Organization, Membership, OrgInvite
│   │   ├── user_routes_models.py  # Saved routes
│   │   ├── user_tx_models.py      # User transactions
│   │   ├── user_contacts_models.py# Contacts
│   │   ├── user_wallets_models.py # Linked wallets
│   │   ├── user_api_keys_models.py# User/org-scoped keys
│   │   ├── notification_models.py # Preferences + known devices
│   │   └── *_schemas.py           # Pydantic request/response per domain
│   │
│   ├── services/  (60+ modules — highlights)
│   │   ├── execution_engine.py    # Cross-chain pipeline + dependency guard
│   │   ├── strategy_engine.py     # Condition evaluator
│   │   ├── sweep_service.py       # Sweep orchestration + AML screening
│   │   ├── deposit_address_service.py / deposit_sweep_service.py # HD deposit addrs + sweep
│   │   ├── split_executor.py / split_engine.py # Split execution + BPS engine + AML gate
│   │   ├── distribution_service.py # Batch distribution (Redis lock, idempotent)
│   │   ├── platform_fee_service.py # 0.5%/flat platform fee accounting
│   │   ├── ledger_service.py / reconciliation_service.py # Double-entry + reconcile
│   │   ├── invoice_service.py     # Commission aggregation + atomic invoice numbering
│   │   ├── webhook_service.py / split_webhook_bridge.py # Merchant webhook delivery + retry
│   │   ├── transaction_matcher.py / polling_service.py / alchemy_webhook_manager.py
│   │   ├── aml_service.py / anomaly_service.py # 3-level AML + z-score
│   │   ├── circuit_breaker.py / kill_switch.py # Fail-closed CB + global kill switch
│   │   ├── alert_service.py / notification_service.py # Telegram/webhook alerts
│   │   ├── key_manager.py / signing_audit.py / signing_rate_limit.py # Signer hardening
│   │   ├── auth_service.py / email_auth_service.py / password_service.py # Identity
│   │   ├── siwe_service.py / wallet_session.py # SIWE wallet sessions
│   │   ├── org_service.py / org_invite_service.py # Orgs + invites
│   │   ├── account_deletion_service.py / account_linking_service.py # GDPR + linking
│   │   ├── device_fingerprint.py / auth_audit.py # Known-device + auth audit
│   │   ├── user_api_key_service.py / key_usage_service.py # User keys + usage
│   │   ├── nonce_manager.py / wallet_manager.py / rpc_manager.py / gas_estimator.py
│   │   ├── cache_service.py / idempotency_service.py / rate_limiter.py / hmac_service.py
│   │   └── spending_policy.py / state_machine.py / metrics.py / external_health.py
│   │
│   ├── middleware/    # correlation, structured_logging, rate_limit, idempotency,
│   │                  # input_sanitization, api_auth, error_handler, request_context
│   ├── security/      # auth, api_keys, input_validator, webhook_verifier
│   ├── tasks/         # Celery: sweep, webhook, periodic, notification
│   └── jobs/          # reconciliation_job
│
├── alembic/versions/              # 0000–0040 (41 migrations)
├── infrastructure/kms_policy.json # AWS KMS IAM policy
├── data/sanctions/ofac_sdn.json   # OFAC SDN sanctioned addresses
├── tests/                         # pytest suite (async, SQLite)
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Quick Start

```bash
# 1. Install
cd rpagos-backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in: DATABASE_URL, REDIS_URL, ALCHEMY_API_KEY, SWEEP_PRIVATE_KEY,
#          HMAC_SECRET, AUTH_JWT_SECRET, RESEND_API_KEY

# 3. Database
alembic upgrade head

# 4. Run (dev mode)
python -m uvicorn app.main:app --reload
# -> http://localhost:8000
# -> Swagger docs: http://localhost:8000/docs (DEBUG=true only)

# 5. Test
pytest -v
# SQLite-backed run (no Postgres needed):
DATABASE_URL="sqlite+aiosqlite:///./.test.db" pytest -q
```

## API Endpoints

### Transactions & Compliance
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/tx/callback` | Alchemy webhook callback (HMAC verified) |
| GET | `/api/v1/tx/{fiscal_ref}` | Get transaction by fiscal ref |
| GET | `/api/v1/anomalies` | List anomaly alerts (z-score) |
| POST | `/api/v1/dac8/generate` | Generate DAC8 XML report |

### Forwarding, Sweeps, Distribution & Splits
| Method | Endpoint | Description |
|---|---|---|
| POST/GET | `/api/v1/sweep/rules` | Create / list forwarding rules |
| POST | `/api/v1/sweep/execute` | Trigger sweep execution |
| WS | `/ws/sweep-feed` | Real-time sweep events |
| POST | `/api/v1/distribution/...` | Batch distribution lists + execute |
| POST/GET | `/api/v1/splits/...` | Multi-wallet split contracts |
| POST | `/api/v1/execution/plan` (+ `/execute`, `/{id}`) | Cross-chain plan (dry-run → execute) |
| POST/GET/PATCH/DELETE | `/api/v1/strategies/...` (+ `/simulate`) | Conditional automation DSL |

### Merchant B2B (Payments, Profile, Invoices)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/merchant/payment-intent` | Create payment intent |
| GET | `/api/v1/merchant/payment-intent/{id}` | Get intent status |
| POST | `/api/v1/merchant/webhook/register` | Register webhook URL |
| POST | `/api/v1/merchant/webhook/test` | Send test event |
| GET | `/api/v1/merchant/transactions` | List merchant transactions |
| GET/PUT | `/api/v1/merchant/profile` | Read / upsert billing anagrafica (org-scoped) |
| POST/GET | `/api/v1/merchant/invoices` | Create draft / list commission invoices |
| GET | `/api/v1/merchant/invoices/{id}` | Get single invoice |
| POST | `/api/v1/merchant/invoices/{id}/issue` | Draft → issued (requires complete client billing) |
| POST/GET | `/api/v1/keys` (+ `/{id}/usage`, `/{id}/revoke`) | Merchant API keys (scopes, usage) |

### Identity & Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/signup` · `/login` | Email + password (bcrypt) |
| POST | `/api/v1/auth/verify-email` · `/resend-verification` | Email verification |
| POST | `/api/v1/auth/request-password-reset` · `/reset-password` | Password reset |
| GET | `/api/v1/auth/check-email` | Email availability |
| POST | `/api/v1/auth/wallet-session` | SIWE (EIP-4361) wallet login |
| POST | `/api/v1/auth/refresh` · `/logout` | Token rotation / revoke |
| GET | `/api/v1/auth/me` | Current user |

### User Account (JWT-scoped)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/user/account/status` · `/sessions` · `/known-devices` | Account + device/session mgmt |
| POST | `/api/v1/user/account/sessions/revoke-all` · `/delete` · `/delete/cancel` | Revoke / GDPR delete |
| GET/POST | `/api/v1/user/account/auth-methods` (+ link/unlink Google/GitHub, add/remove password) | Sign-in methods |
| GET/POST/PATCH/DELETE | `/api/v1/user/routes` · `/transactions` · `/contacts` · `/wallets` | Persistent user data (+ bulk-import) |
| GET/POST/PATCH/DELETE | `/api/v1/user/api-keys` (+ `/available-scopes`) | User/org-scoped API keys |
| GET/PATCH | `/api/v1/user/notifications/preferences` | Notification preferences |

### Organizations (Multi-tenancy)
| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/api/v1/organizations` | List / create orgs |
| POST | `/api/v1/organizations/switch` | Set active org |
| PATCH | `/api/v1/organizations/{id}` | Update org |
| GET/PATCH/DELETE | `/api/v1/organizations/{id}/members/...` | Members + role management |
| GET/POST/DELETE | `/api/v1/organizations/{id}/invites` | Manage invites |
| GET/POST | `/api/v1/invites/{token}/preview` · `/accept` · `/decline` | Public invite flow |

### Internal (oracle / signing / rate-limit)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/internal/signing/check` · `/audit` | Pre-signing validation + immutable audit |
| POST | `/api/internal/oracle/sign-digest` | KMS/local digest signing |
| POST | `/api/internal/ratelimit/check` | Distributed rate-limit check |

### AML
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/aml/check` | Full AML check (screening + monitoring) |
| GET | `/admin/aml/alerts` | List alerts (filter by status/sender, paginated) |
| POST | `/admin/aml/alerts/{id}/review` | Review alert (reviewed/escalated/dismissed) |
| POST | `/admin/aml/sanctions/update` | Upload sanctions list or load built-in OFAC file |
| GET | `/admin/aml/stats` | 24h alert statistics |

### Dashboard, Ledger & Health
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/dashboard/stats` | Aggregated org dashboard stats |
| GET | `/api/v1/ledger/...` | Double-entry ledger + CSV export |
| GET | `/health` · `/health/live` · `/health/ready` | Basic / liveness / readiness |
| GET | `/health/deep` | 5-component check (Postgres, Redis, Celery, RPC, KMS) |
| GET | `/health/sweep` · `/health/rpc` · `/health/dependencies` · `/health/config` · `/health/reconciliation` | Targeted health |
| GET | `/metrics` | Prometheus metrics |

## Security Architecture

### Identity & Sessions
- **Auth**: email+password (bcrypt) end-user login, SIWE wallet sessions (EIP-4361). Social login (Google/GitHub) was removed from the product.
- **JWT access/refresh** (HS256, `AUTH_JWT_SECRET` ≥64 chars in prod) with server-side session records and refresh rotation.
- **Account settings**: add/remove password (a user must always retain at least one sign-in method).
- **Known-device + session management**: device fingerprinting, list/revoke sessions, GDPR soft-delete with cancellation window.
- **Email verification + password reset** via single-use tokens (Resend API; `EMAIL_DEV_MODE=true` logs links locally).

### Organizations (Multi-tenancy)
- Users belong to organizations via memberships with roles (**viewer < operator < admin**).
- `require_org_role("operator")` dependency gates write endpoints; the active org is resolved from `users.active_org_id`.
- API keys and linked wallets are **org-scoped** (migrations 0029–0030). Merchant billing endpoints derive `owner_address` from the active org's primary EVM wallet.
- Invite flow: tokenized invites with public preview/accept/decline.

### Signing Protection
- Oracle signing guard validates chain, recipient, amount bounds, deadline (max 10min).
- Per-wallet rate limiting (10/min, 50/hr via Redis INCR+EXPIRE); per-IP 20/min; global 100/min.
- Server-side nonce deduplication via Redis SETNX (1h TTL).
- Immutable audit log: every signing request (approved/denied) in Postgres.

### KMS Hardening
- IAM policy restricts `kms:Sign` to backend role only (`ECDSA_SHA_256`); destructive ops require MFA + admin role.
- Local rate limiter (60/min, 500/hr) as defence-in-depth; every KMS op logged to `kms_audit_log`.
- Key rotation: sign with active key, verify with active + previous keys.

### AML (3-Level) + Split Gate
1. **Address Screening** (blocks): OFAC SDN, EU sanctions, local DB, hardcoded list.
2. **Transaction Monitoring** (flags): single >€1K, daily >€5K, monthly >€15K (DAC8 KYC), velocity >10/h, structuring.
3. **Reporting**: AML alerts persisted for compliance review.
- **Split AML gate**: screens ALL recipients pre-execution; anti-structuring on split plans.

### Circuit Breakers & Kill Switch
- Redis-backed CB with Lua atomic transitions; per-chain RPC breakers.
- **Fail-closed for financial ops**: sweep/transfer/execution blocked when Redis/Postgres/RPC down.
- Global **kill switch** to halt financial operations on demand.

## Alert Service

| Alert Type | Severity | Trigger |
|---|---|---|
| `signing_down` | EMERGENCY | Circuit breaker opened on signing path |
| `kms_rate_limit` | CRITICAL | Local KMS rate limit exceeded |
| `redis_down` | EMERGENCY | Redis unreachable |
| `rpc_down` | WARNING | Chain RPC unreachable |
| `sweep_failed` | CRITICAL | Sweep execution failed |
| `aml_block` | INFO | Transaction blocked by AML |
| `balance_low` | WARNING | Master wallet below threshold |
| `cb_recovery` | INFO | Circuit breaker recovered |

Cooldown: EMERGENCY 1min, CRITICAL 5min, WARNING 15min, INFO 60min.

## Database Migrations

`alembic upgrade head` applies all 41 migrations (0000–0040). All are additive (expand-phase: no destructive drops/renames) and dual-dialect (PostgreSQL prod, SQLite tests).

```
0000 Bootstrap legacy            0014 AML tables                 0028 User-scoped API keys
0001 Double-entry ledger         0015 KMS audit log              0029 Organizations + memberships
0002 Legacy forwarding tables    0016 API keys table             0030 Org-scope keys + wallets
0003 Command center models       0017 Platform fee fields        0031 Email+password auth
0004 Merchant B2B tables         0018 API key scopes + tracking  0032 Auth-method columns (legacy)
0005 Late payment policy         0019 Unique matched_tx_hash     0033 Forwarding rules version
0006 Matching v2 amount track    0020 API key bcrypt v2          0034 Audit logs SET NULL
0007 Deposit address matching    0021 Auth tables (users)        0035 Split contracts owner_address
0008 Sweep fields + statuses     0022 User routes                0036 Split exec unique src tx
0009 Sweep dedup index           0023 User transactions          0037 account_type (indiv/merchant)
0010 Split contracts tables      0024 User contacts              0038 Signup profile fields
0011 Daily snapshots + HMAC      0025 Notifications + devices    0039 Merchant profiles (billing)
0012 Performance indexes         0026 User wallets (SIWE)        0040 Invoices + counters
0013 Signing audit log           0027 User GDPR soft-delete
```

## Environment Variables

See `.env.example` for full documentation. Key variables:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL async URL (`sqlite+aiosqlite://` in tests) |
| `REDIS_URL` | Prod | Redis URL (cache, rate limit, idempotency, sessions) |
| `ALCHEMY_API_KEY` | Yes | Alchemy RPC |
| `SWEEP_PRIVATE_KEY` | Yes* | Hot wallet key (*unless SIGNER_MODE=kms) |
| `SIGNER_MODE` | No | `local` (default), `kms`, or `vault` |
| `KMS_KEY_ID` | If kms | AWS KMS key ID |
| `DEPOSIT_MASTER_KEY` / `DEPOSIT_MASTER_SEED` | Yes | HD deposit-address derivation |
| `HMAC_SECRET` | Prod | ≥32 chars, webhook/API verification |
| `AUTH_JWT_SECRET` | Prod | HS256 access-token secret, ≥64 chars in prod |
| `RESEND_API_KEY` | If emails | Resend API key (`re_...`); skipped when `EMAIL_DEV_MODE=true` |
| `EMAIL_FROM` / `EMAIL_DEV_MODE` | No | Sender address / log-links-locally toggle |
| `FRONTEND_URL` | Prod | Base URL for verification/reset links + CORS |
| `PLATFORM_FEE_ENABLED` / `PLATFORM_FEE_BPS` / `PLATFORM_TREASURY_ADDRESS` | No | Platform fee accounting |
| `TREASURY_ADDRESSES_JSON` | No | Per-chain treasury map for reconciliation |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALERT_CHAT_ID` / `ALERT_WEBHOOK_URL` | No | Alert delivery |
| `SENTRY_DSN` / `OTEL_ENDPOINT` | No | Error tracking / tracing |
| `RUN_MIGRATIONS_ON_BOOT` | No | Run Alembic on startup (Render Pre-Deploy guard) |

## Production

```bash
# Docker
docker build -t rpagos-backend .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/rpagos \
  -e REDIS_URL=redis://redis:6379/0 \
  -e HMAC_SECRET=your-64-char-hex-secret \
  -e AUTH_JWT_SECRET=your-64-char-hex-secret \
  rpagos-backend

# Docker Compose (PostgreSQL + Redis + Celery)
docker-compose up -d

# Load OFAC sanctions
curl -X POST http://localhost:8000/admin/aml/sanctions/update
```
