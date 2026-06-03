# RSends — GO-LIVE RUNBOOK (attivazione sicurezza)

> Questo runbook è il **layer di attivazione-sicurezza** sopra i doc di deploy infra
> esistenti (`rpagos-backend/DEPLOY.md`, `rpagos-backend/DEPLOY_CHECKLIST.md`).
> Copre **solo** le attivazioni delle remediation dell'audit (C1–C3, H1–H6, M1–M12):
> i fix sono già in codice, ma **molti sono dormienti/gated da config** e vanno
> accesi **nel giusto ordine**, altrimenti in un deploy fresco alcuni buchi restano aperti.
>
> Infra di base (non ripetuta qui): backend su **Render** (`scripts/entrypoint.sh` esegue
> già `alembic upgrade head` + `uvicorn app.main:app --workers 1`; Celery sweep/confirm/
> notify/analytics + beat via docker-compose); frontend su **Vercel** (`next build`).
>
> Convenzioni: `<…>` = placeholder da sostituire. Env pydantic = UPPERCASE del campo
> (nessun prefix). Token admin = header `X-Admin-Token` con valore `= HMAC_SECRET`.

---

## 0. Matrice fix → attivazione (cosa succede se NON la fai)

| Fix | Env/Azione | Default | Se NON attivato |
|---|---|---|---|
| H3/C2 | `INTERNAL_PROXY_SECRET` uguale su backend+Next | vuoto | firma bloccata in prod (fail-closed) ✋ |
| H6 | `DEBUG=false` | — | strong-tier non attivo (Redis in chiaro, JWT corto, ecc.) |
| M8 | `API_GET_DENY_BY_DEFAULT` | **True** ✅ | (già attivo) |
| M5 | `RATELIMIT_TRUSTED_PROXY_HOPS` | `1` | IP spoofabile dietro >1 proxy |
| H4 | deploy BE→FE, poi `WALLET_AUTH_ALLOW_LEGACY=false` | `true` | **firma wallet ancora replayabile** ⚠️ |
| M1-A | `ORACLE_SIGNER_MODE=kms/remote` + `setOracleSigner` su V4 | `local` | **chiave oracle ancora nel web tier** ⚠️ |
| M1-B | deploy V5/V6 + `setOracleSigners` + `version:'v6'` | V4 single | single-point-of-forgery (chiave singola) |
| M11 | `ADMIN_TOTP_SECRET` | vuoto | **admin senza 2FA** (solo password) ⚠️ |
| — | `ADMIN_ALLOW_BEARER` vuoto in prod | vuoto ✅ | (Bearer no-2FA già disabilitato in prod) |

---

## 1. Segreti — genera e setta

Genera (una volta) e inserisci nei pannelli **Render** (backend) e **Vercel** (frontend):

```bash
# Segreto condiviso Next↔backend (H3) — DEVE essere IDENTICO sui due lati
openssl rand -hex 32        # → INTERNAL_PROXY_SECRET

# Webhook HMAC + admin token (X-Admin-Token == questo valore)
openssl rand -hex 32        # → HMAC_SECRET

# Password dashboard admin
openssl rand -hex 32        # → ADMIN_SECRET

# JWT utenti (HS256) — deve essere >= 64 char in prod (H6)
openssl rand -hex 32        # → AUTH_JWT_SECRET   (hex di 32 byte = 64 char)
```

### Env **required in prod** (altrimenti `validate_settings` fa fail-fast all'avvio — H6)
Backend (Render → Environment):
```
DEBUG=false
REDIS_URL=rediss://<host>:6379/0          # TLS obbligatorio in prod
CELERY_BROKER_URL=rediss://<host>:6379/1
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>   # NO "rpagos:password@"
HMAC_SECRET=<hex32>
INTERNAL_PROXY_SECRET=<hex32>             # uguale a Next
GOOGLE_OAUTH_CLIENT_ID=<...>
AUTH_JWT_SECRET=<hex32>                    # >= 64 char
DEPOSIT_MASTER_KEY=<0x… 64 hex>
ALCHEMY_API_KEY=<...>
CORS_ORIGINS=https://<dominio>            # niente wildcard
```
Frontend (Vercel → Environment, **server-only**, NON `NEXT_PUBLIC_`):
```
RPAGOS_BACKEND_URL=https://<backend-host>
INTERNAL_PROXY_SECRET=<hex32>             # IDENTICO al backend
ADMIN_SECRET=<hex32>
```

> ⚠️ **Fail-closed**: se `INTERNAL_PROXY_SECRET` manca o è diverso tra i due lati,
> la firma oracle si blocca (403/503). Settalo su **entrambi** PRIMA di aprire traffico.

---

## 2. Deploy backend + verifica base

1. Setta tutte le env (sez. 1) su Render.
2. Deploy (push). `entrypoint.sh` esegue **automaticamente** `alembic upgrade head`
   (head atteso = **0036**) e avvia `uvicorn --workers 1`.
3. Avvia i worker Celery (sweep/confirm/notify/analytics + beat) — vedi docker-compose.
4. Verifica liveness/readiness:
```bash
curl -fsS https://<backend-host>/health            # {"status":"healthy", "redis":"connected", ...}
curl -fsS https://<backend-host>/health/ready       # 200 se db+redis ok, 503 altrimenti
```
5. Verifica migrazioni (opzionale, dal container backend):
```bash
cd /app && alembic current     # deve mostrare 0036 (head)
```

---

## 3. Sequenza di attivazione ORDINATA

Le dipendenze contano: esegui **in quest'ordine**.

### 3.1 — H3/C2 (segreto interno) — *prima del traffico*
Già fatto in sez. 1 (env su entrambi i lati). Verifica:
```bash
# Browser/anonimo NON deve raggiungere gli endpoint interni (denylist proxy H3)
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST https://<dominio>/api/backend/api/internal/signing/audit   # atteso: 404
```

### 3.2 — H6 (hardening prod)
Già attivo con `DEBUG=false`. Verifica via endpoint admin-gated:
```bash
curl -s -H "X-Admin-Token: <HMAC_SECRET>" https://<backend-host>/health/config
# "environment":"production", e SIGNER_MODE/KMS coerenti
```

### 3.3 — M8 (deny-by-default GET) + M5 (rate-limit)
- `API_GET_DENY_BY_DEFAULT` è **già True** (nessuna azione; kill-switch = `false`).
- Setta su Vercel: `RATELIMIT_TRUSTED_PROXY_HOPS=1` (alza se ci sono più proxy davanti a Next).

### 3.4 — H4 (anti-replay firma wallet) — *flip a 2 fasi*
1. Deploy **backend** poi **frontend** con `WALLET_AUTH_ALLOW_LEGACY=true` (default) — il
   nuovo schema session-HMAC e il legacy convivono durante il rollout.
2. Verifica che il dApp autentichi le mutate (la sessione wallet si crea con 1 firma).
3. **Chiudi il legacy**: setta `WALLET_AUTH_ALLOW_LEGACY=false` sul backend e redeploy.
   Da qui le vecchie firme bearer replayabili sono rifiutate.

---

## 4. M1-A — Oracle in KMS sul rail V4 (NESSUN redeploy contratti)

`FeeRouterV4` ha `setOracleSigner(address) onlyOwner` e `oracleSigner` mutabile → si può
spostare la firma oracle in **KMS** sul contratto V4 **già vivo**, togliendo
`ORACLE_PRIVATE_KEY` dal web tier.

```bash
# 1) Crea la key KMS dedicata all'oracle (secp256k1, sign/verify)
aws kms create-key --key-spec ECC_SECG_P256K1 --key-usage SIGN_VERIFY \
  --description "RSends oracle signer" --region <AWS_REGION>
# → annota il KeyId  → ORACLE_KMS_KEY_ID
```

```
# 2) Backend (Render): abilita il signer KMS dedicato
ORACLE_SIGNER_MODE=kms
ORACLE_KMS_KEY_ID=<KeyId>
AWS_REGION=<region>
# (IAM del backend deve avere kms:Sign + kms:GetPublicKey su quel key)

# 3) Frontend (Vercel): delega la firma al backend (la chiave NON sta più nel web tier)
ORACLE_SIGNER_MODE=remote
# ORACLE_PRIVATE_KEY può essere rimossa
```

```bash
# 4) Ricava l'address Ethereum della key KMS (deriva dalla pubkey).
#    Comando one-off DAL backend (env KMS già settate):
python -c "import asyncio; from app.services.key_manager import get_oracle_signer; \
print(asyncio.run(get_oracle_signer().get_address()))"
# → <KMS_ORACLE_ADDR>

# 5) Punta il contratto V4 vivo alla nuova chiave (owner key, idealmente HW/cold):
cast send <V4_ADDR> "setOracleSigner(address)" <KMS_ORACLE_ADDR> \
  --rpc-url <CHAIN_RPC_URL> --private-key <OWNER_PRIVATE_KEY>

# 6) Verifica
cast call <V4_ADDR> "oracleSigner()" --rpc-url <CHAIN_RPC_URL>   # == <KMS_ORACLE_ADDR>
```

> Ripeti `setOracleSigner` su ogni chain con un V4 vivo (Base 8453, Ethereum 1, …).
> Smoke: una transazione di test passa il **self-check M2** (dominio match) e va on-chain (sez. 7).

---

## 5. M1-B — Multisig V5/V6 (deploy) — *raccomandato: chiude il single-point-of-forgery*

> Opzionale ma è ciò che **davvero** elimina "chiave singola = forgery totale". Richiede
> deploy di un nuovo router (V6 è multisig-only) + N firmatari KMS distinti.

```bash
# 1) Crea N key KMS distinte (es. 3 per un 2-of-3) e ricava i loro address
#    (ripeti il comando python della sez. 4.4 con ORACLE_KMS_KEY_ID=<ognuna>).
#    Ordina gli address in ASCENDING (richiesto dal contratto), senza duplicati.

# 2) Deploy FeeRouterV6 sulla chain target.
#    Constructor: (permit2, treasury, address[] initialSigners, uint8 threshold,
#                  swapRouter, weth, usdt, owner)
cd contracts
export PRIVATE_KEY=<DEPLOYER_KEY>
forge script script/DeployMultiChain.s.sol:DeployMultiChain \
  --rpc-url <CHAIN_RPC_URL> --broadcast --slow -vvv
# → annota <V6_ADDR>
#   (se lo script non parametrizza signers/threshold, deploya con forge create
#    passando i constructor-args, oppure usa setOracleSigners al passo 3.)
```

```bash
# 3) Configura i firmatari (se non già nel constructor) — owner-only, ascending, no dup:
cast send <V6_ADDR> "setOracleSigners(address[],uint8)" \
  "[<addr1>,<addr2>,<addr3>]" 2 \
  --rpc-url <CHAIN_RPC_URL> --private-key <OWNER_PRIVATE_KEY>

# 4) Verifica multisig
cast call <V6_ADDR> "getOracleSigners()"  --rpc-url <CHAIN_RPC_URL>
cast call <V6_ADDR> "oracleThreshold()"   --rpc-url <CHAIN_RPC_URL>     # == 2
cast call <V6_ADDR> "domainSeparator()"   --rpc-url <CHAIN_RPC_URL>     # usato da M2
```

```
# 5) Backend (Render): set multi-key
ORACLE_SIGNER_MODE=kms
ORACLE_KMS_KEY_IDS=<KeyId1>,<KeyId2>,<KeyId3>     # CSV; sostituisce ORACLE_KMS_KEY_ID

# 6) Frontend (Vercel): punta la chain al router V6 + attiva il path bytes[]
NEXT_PUBLIC_FEE_ROUTER_V4_<CHAIN>=<V6_ADDR>        # es. _BASE, _ETH
```

```diff
# 7) lib/contractRegistry.ts — aggiungi version:'v6' alla entry della chain:
   <CHAINID>: {
     chainId:   <CHAINID>,
     feeRouter: <chain>FeeRouter(),
+    version:   'v6',
     ...
   }
```

8. Redeploy Vercel. Da qui l'oracle produce `bytes[]` e il dApp chiama i 4 entrypoint V6
   con `oracleSignatures` (bytes[]). **M2** verifica al primo sign che il dominio
   (`FeeRouterV6`/`6`) combaci con `domainSeparator()` on-chain (fail-closed su drift).

> CCIP cross-chain **non è in scope** (sender/receiver non deployati, registry ZERO).

---

## 6. M11 — Admin 2FA (TOTP)

1. Login bootstrap (solo password) → la sessione è **setup-only** (può solo arruolare TOTP).
2. Ottieni il secret/QR:
```bash
curl -s -X POST https://<dominio>/api/admin/2fa/setup \
  -H "Cookie: admin_session=<bootstrap_session>"
# → { secret, otpauthUrl, qr } : aggiungi a un'app TOTP
```
3. Setta su Vercel: `ADMIN_TOTP_SECRET=<secret base32>` e redeploy.
4. **Re-login con password + codice TOTP** → ottieni una sessione **full** (azioni admin).
5. Lascia `ADMIN_ALLOW_BEARER` **vuoto** in prod (il fallback `Bearer ADMIN_SECRET`
   senza 2FA resta disabilitato).

---

## 7. Verifica post-deploy (smoke-test)

```bash
DOMAIN=https://<dominio>; ADMIN="X-Admin-Token: <HMAC_SECRET>"

# H1/H2/M8 — ledger anonimo negato; con admin token ok
curl -s -o /dev/null -w "ledger anon: %{http_code}\n"  $DOMAIN/api/backend/api/v1/ledger/accounts            # 401/404
curl -s -o /dev/null -w "ledger admin: %{http_code}\n" -H "$ADMIN" $DOMAIN/api/backend/api/v1/ledger/accounts # 200

# C3 — mint API key anonimo negato
curl -s -o /dev/null -w "keygen anon: %{http_code}\n" -X POST \
  $DOMAIN/api/backend/api/v1/keys/generate -d '{"owner_address":"0x..","scope":"admin"}'                      # 401

# H3 — endpoint interni non raggiungibili dal browser
curl -s -o /dev/null -w "internal audit: %{http_code}\n" -X POST \
  $DOMAIN/api/backend/api/internal/signing/audit                                                              # 404

# M7 — health/config admin-gated
curl -s -o /dev/null -w "health/config anon: %{http_code}\n" $DOMAIN/health/config                           # 403
curl -s -o /dev/null -w "health/config admin: %{http_code}\n" -H "$ADMIN" $DOMAIN/health/config              # 200

# M9 — spending-limits richiede wallet-auth
curl -s -o /dev/null -w "spending anon: %{http_code}\n" \
  "$DOMAIN/api/backend/api/v1/forwarding/spending-limits?source_address=0x0000000000000000000000000000000000000001" # 401

# M1/M2 — dominio on-chain coerente + firma reale accettata
cast call <ROUTER_ADDR> "domainSeparator()" --rpc-url <CHAIN_RPC_URL>
# → poi una transazione reale di piccolo importo deve andare a buon fine
```

---

## 8. Kill-switch / rollback (tutti via env, niente redeploy codice)

| Variabile | Valore di rollback | Effetto |
|---|---|---|
| `API_GET_DENY_BY_DEFAULT` | `false` | riapre il fallback GET pubblico (annulla M8) |
| `WALLET_AUTH_ALLOW_LEGACY` | `true` | riaccetta le firme wallet legacy (annulla H4) |
| `ADMIN_ALLOW_BEARER` | `1` | riabilita `Bearer ADMIN_SECRET` (no-2FA) |
| `ORACLE_SIGNER_MODE` | `local` (Next) | torna alla chiave oracle locale (annulla M1-A) |

In emergenza on-chain, `pause()` (owner) su FeeRouterV6 / RSendBatchDistributor ferma il rail.

---

## 9. Residui (FUORI da questo runbook)

- **Finding LOW** non chiusi: chiave Pimlico nel bundle client, CSP `script-src 'unsafe-inline'`,
  endpoint oracle `_debug` in prod (espone signer/dominio). Hardening cosmetico/minore.
- **CCIP** non deployato → cross-chain non attivabile finché non si deployano sender/receiver.
- **Validazione mancante**: staging soak con Redis/DB/RPC reali (incl. test fail-closed),
  load/stress sui path di firma+sweep, e **re-review indipendente** del codice nuovo
  introdotto dalle remediation (`/api/internal/oracle`, `/api/internal/ratelimit`, ticket WS,
  remote signer). Vedi *Verdetto* nel report di audit.

---

### Riferimenti
- Report audit completo + dettaglio di ogni fix: `~/.claude/plans/controlla-tutti-i-file-piped-bee.md`
- Deploy infra base: `rpagos-backend/DEPLOY.md`, `rpagos-backend/DEPLOY_CHECKLIST.md`
- CI: `.github/workflows/ci.yml` (forge test + pytest + tsc)
