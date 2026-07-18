# RSends Security Checklist

API key inventory, rotation procedures, and security hardening.

---

## API Keys & Secrets Inventory

### Backend (server-side only — `.env`)

| Secret | Where Used | How to Rotate | Rotation Frequency |
|---|---|---|---|
| `HMAC_SECRET` | `hmac_service.py` — signs/verifies callback HMAC-SHA256. Also used by Next.js proxy (`app/api/tx/callback/route.ts`). | 1. Generate new secret (`openssl rand -hex 32`). 2. Update `.env` on backend **and** Next.js server env. 3. Restart both services. No downtime if done atomically. | Every 90 days, or immediately if compromised. |
| `SWEEP_PRIVATE_KEY` | `wallet_manager.py` — hot wallet signing for sweep transactions. | 1. Deploy a new hot wallet. 2. Transfer remaining funds from old wallet. 3. Update `.env` with new key. 4. Update forwarding rules if the hot wallet address changed. | Only on compromise. Keep balance minimal. |
| `ALCHEMY_API_KEY` | `rpc_manager.py`, `gas_estimator.py` — all RPC calls (gas, broadcast, receipts). Also exposed as `NEXT_PUBLIC_ALCHEMY_API_KEY` in frontend. | 1. Create new key in Alchemy Dashboard. 2. Update `.env` (backend) and `.env.local` (frontend). 3. Redeploy. Old key can be revoked after deploy. | Every 90 days. |
| `KMS_KEY_ID` | `wallet_manager.py` — AWS KMS signing (when `SIGNER_MODE=kms`). | Rotation managed by AWS KMS automatic key rotation policy. Enable yearly rotation in AWS Console. | Automatic (AWS-managed). |
| `SENTRY_DSN` | `main.py` — error tracking initialization. | Regenerate in Sentry > Project Settings > Client Keys. | Only on compromise. |
| `TELEGRAM_BOT_TOKEN` | `notification_service.py` — sweep/alert notifications. | 1. Revoke via BotFather `/revoke`. 2. Create new token. 3. Update `.env`. | Only on compromise. |
| `DATABASE_URL` | `session.py`, `config.py` — PostgreSQL connection. Contains password. | 1. Change DB user password. 2. Update connection string in `.env`. 3. Restart backend. | Every 90 days for password. |
| `REDIS_URL` | `cache_service.py` — cache, rate limiting, idempotency. Contains password if auth enabled. | Update password in Redis config and `.env`. Restart backend. | Every 90 days if auth enabled. |

### Frontend (browser-visible — `.env.local`)

| Secret | Where Used | How to Rotate | Rotation Frequency |
|---|---|---|---|
| `NEXT_PUBLIC_WC_PROJECT_ID` | `providers.tsx` — WalletConnect Cloud project. | Regenerate in WalletConnect Cloud Dashboard. | Only on compromise. |
| `NEXT_PUBLIC_ALCHEMY_API_KEY` | `contractRegistry.ts` — client-side RPC calls. | Same as backend `ALCHEMY_API_KEY` (may be same key). Apply domain allowlist in Alchemy Dashboard. | Every 90 days. |
| `ORACLE_PRIVATE_KEY` | `app/api/oracle/sign/route.ts` — server-side EIP-712 signing. **NOT** `NEXT_PUBLIC_`, only accessible in API routes. | 1. Generate new key. 2. Update `authorizedOracle` in FeeRouterV4 contract (`setOracle()`). 3. Update `.env.local`. 4. Redeploy. | Every 90 days, or on compromise. |
| `HMAC_SECRET` | `app/api/tx/callback/route.ts` — server-side HMAC computation. **NOT** `NEXT_PUBLIC_`, only accessible in API routes. | Must match backend `HMAC_SECRET`. Rotate both simultaneously. | Every 90 days. |

---

## Security Hardening Checklist

### Pre-Production

- [ ] **HMAC_SECRET**: Changed from default (`change-me-in-production`), >= 32 chars
- [ ] **SWEEP_PRIVATE_KEY**: Valid 0x-prefixed 64-char hex, hot wallet funded with minimal ETH
- [ ] **ORACLE_PRIVATE_KEY**: Set and matching the on-chain `authorizedOracle` address
- [ ] **DEBUG=false**: Disables `/docs` endpoint, verbose logging, and development warnings
- [ ] **CORS_ORIGINS**: Set to production domains only (not `localhost`)
- [ ] **Alchemy API Key**: Domain allowlist configured in Alchemy Dashboard
- [ ] **NEXT_PUBLIC_HMAC_SECRET**: Removed from `.env.local` (HMAC now computed server-side)
- [ ] **CSP headers**: Verified in `next.config.mjs` — no `unsafe-eval` if possible
- [ ] **Rate limiting**: Redis connected, middleware active
- [ ] **Idempotency**: Redis connected, fail-closed mode active

### Ongoing

- [ ] **Dependency audit**: `npm audit` and `pip audit` run monthly
- [ ] **Key rotation**: All keys rotated per schedule above
- [ ] **Hot wallet balance**: Monitored via `/health/sweep`, alerts if below threshold
- [ ] **Circuit breakers**: Monitored via `/health/dependencies`
- [ ] **Anomaly detection**: Reviewed weekly via `/api/v1/anomalies`
- [ ] **DAC8 compliance**: Reports generated quarterly via `/api/v1/dac8/generate`

### Incident Response

1. **Compromised HMAC_SECRET**: Rotate immediately on both backend and Next.js. All in-flight requests with old signature will fail (acceptable).
2. **Compromised SWEEP_PRIVATE_KEY**: Immediately pause all forwarding rules. Deploy new wallet. Transfer funds. Update key.
3. **Compromised ORACLE_PRIVATE_KEY**: Call `setOracle(newAddress)` on FeeRouterV4. Rotate key. Redeploy.
4. **Compromised ALCHEMY_API_KEY**: Revoke in Alchemy Dashboard. Create new key. Redeploy both frontend and backend.

---

## Environment Variable Classification

| Classification | Variables | Exposure |
|---|---|---|
| **Critical secrets** (never in browser) | `HMAC_SECRET`, `SWEEP_PRIVATE_KEY`, `ORACLE_PRIVATE_KEY`, `KMS_KEY_ID`, `DATABASE_URL` | Server-only `.env` |
| **Service tokens** (server-only) | `SENTRY_DSN`, `TELEGRAM_BOT_TOKEN`, `REDIS_URL`, `CELERY_BROKER_URL` | Server-only `.env` |
| **Public API keys** (browser-safe, domain-restricted) | `NEXT_PUBLIC_WC_PROJECT_ID`, `NEXT_PUBLIC_ALCHEMY_API_KEY`, `NEXT_PUBLIC_TREASURY_ADDRESS` | `.env.local` with `NEXT_PUBLIC_` prefix |
