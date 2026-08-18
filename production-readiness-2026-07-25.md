# Production-readiness audit — 2026-07-25

Audit read-only eseguito in sessione (Claude Code); ogni claim ha l'evidenza del comando o
probe che l'ha prodotta. Nessuna modifica al codice. Baseline: origin/main `f5390379`
(merge PR #74, 2026-07-24).

## Verdetto sintetico

| Area | Stato | Nota |
|---|---|---|
| Codice / suite di test | 🟢 | backend 768 passed / 26 skipped / **0 failed** (71s, PG+Redis reali); contracts 86/86; `next build` OK |
| Invarianti di sicurezza | 🟢 | recipient gate, rate-limit fail-closed, tenant 404, auth 401 verificati su codice + prod |
| CI GitHub | 🔴 | **billing Actions fallito** — nessun job parte da ~1 giorno; il tip di main non è mai stato verificato dalla CI |
| Deploy pipeline | 🟡 | Vercel e Render auto-deployano main **anche con CI rossa** → codice non verificato va in prod |
| Prod runtime (osservabile) | 🟢 | `/health` healthy, Redis connected, indexer lag 0; fail-closed osservato sui probe |
| Env/config Render | 🟡 | non verificabile direttamente (**Render MCP unauthorized**); DEBUG=false inferito con buona confidenza |
| Mainnet go-live | 🔴 | per design: router v2 fee-less non deployato, `/app` test-locked, "live" env inutilizzabile |

**In sintesi:** per lo scope attuale (prodotto testnet/demo, finestra pre-audit RPagos) il
sistema è in buona forma: codice verificato localmente al 100%, invarianti in piedi, prod
sana. I due problemi operativi reali sono (1) la **CI morta per billing GitHub** — che
combinata con l'auto-deploy significa che ogni push su main va in produzione senza alcuna
verifica automatica — e (2) il solito pacchetto operator-out per il mainnet.

---

## 1. CI rossa su main — causa: billing GitHub Actions

- `gh run view 30094005178` (CI del merge #74): tutti e 4 i job (Backend pytest, E2E Anvil,
  Frontend tsc, Contracts forge) **mai partiti**, annotation: *"The job was not started
  because recent account payments have failed or your spending limit needs to be
  increased"*. Stessa cosa per il run schedulato "On-chain registry verify" di stamattina
  (30151010885).
- Non è una regressione di codice. Ma finché il billing non è sistemato: niente CI su PR,
  niente registry-verify schedulato, e main non ha gate.
- Aggravante verificata: il deploy Vercel production del 2026-07-24 **12:41:23 UTC**
  coincide al secondo col merge di #74 (12:41) → **il codice è andato in prod senza che
  nessun job CI sia mai girato su quel commit**. Render fa lo stesso (deploya main).
- Mitigazione di questa sessione: la suite completa è stata eseguita localmente sul
  medesimo contenuto di main (vedi §2) — 0 failure. Il gap è di processo, non di merito.

**Azione (operatore):** GitHub → Settings → Billing & plans: sistemare pagamento/spending
limit. Poi ri-lanciare la CI su main (`gh run rerun 30094005178` o push vuoto).

## 2. Suite di test — tutte verdi in locale

Ambiente: Redis locale PONG, Postgres locale con i DB `rsends_conc_test` ecc., anvil/forge
presenti.

- **Backend**: `pytest -q` con `CONCURRENCY_TEST_DATABASE_URL=postgresql+asyncpg://emi@localhost:5432/rsends_conc_test`
  → **768 passed, 26 skipped, 0 failed** in 70.8s. Sopra la baseline P3 (730/31) — la
  suite è cresciuta con #74, nessuna regressione.
- **Contracts**: `forge test` → **86 passed, 0 failed** su 4 suite (incl. RSendsSplitRouter
  23 test con fuzz conservation, e la suite v2).
- **Web**: `npm run build` (include typecheck) → exit 0, tutte le route generate.
- Gotcha ambiente (fix locale, non di repo): il venv backend ha gli **shebang stale** al
  vecchio path `/Users/emi/Desktop/wallet-connect/...` (repo spostato). Il symlink python è
  valido → usare `./venv/bin/python -m pytest`, NON `./venv/bin/pytest`. Volendo:
  ricreare il venv.

## 3. Invarianti di sicurezza — verificati

- **Recipient gate**: `grep "PaymentIntent(" app` → il sito di costruzione persistito è
  unico (`intent_service.py:408`). ⚠️ **Divergenza doc**: c'è ora un secondo hit in
  `webhook_service.py:1279`, ma è l'intent **sintetico mai persistito** di
  `_build_test_event_payload` (PR #48, stesso `_build_payload` della produzione) — nessun
  bypass. Il CLAUDE.md dice "grep = one hit": da aggiornare (regola del CLAUDE.md stesso:
  flag + update nella stessa review).
- **Rate limiting**: `ENDPOINT_LIMITS` copre tutte le superfici documentate
  (most-specific-first rispettato); le route non elencate (es. `/auth/login`, `/auth/signup`)
  cadono sui **default per-IP** (GET 60/min, POST 30/min) — nessuna route senza limite.
  Redis giù + `debug=false` → **503 RATE_LIMIT_UNAVAILABLE** (fail-closed, `rate_limit.py`
  dispatch). Verificato in prod: il probe pubblico risponde con header
  `x-ratelimit-limit: 20` (la regola per-IP del checkout).
- **Fail-closed su prod (probe HTTP reali)**:
  - `GET /api/v1/merchant/transactions` senza auth → **401** ✓
  - `GET /api/v1/public/payment-intent/pi_ffff…` → **404** + rate-limit headers ✓
  - `/health/config` e `/admin/approvals` senza `X-Admin-Token` → **422** (header required,
    body = solo l'errore di validazione FastAPI, nessun leak); con token sbagliato → **403** ✓.
    (Il 422-anziché-401 è l'incoerenza di envelope già tracciata nei follow-up, non un buco.)
  - `/docs` e `/openapi.json` → **404** ⇒ `get_settings().debug == False` in prod
    (`main.py:229-233` li monta solo con debug) ⇒ **DEBUG=false confermato indirettamente**,
    e con esso il ramo fail-closed del rate limiting.
- **Test-pin presenti e passanti** (dentro i 768): `test_owner_identity_fallback.py`,
  `test_org_stats_checklist.py`, `test_admin_approvals.py`, `test_logging_redaction.py`,
  `test_indexer_topic_hashes.py`, `test_user_org_payments.py` (cross-org isolation), ecc.
- **Fee claim (flag della memoria fee-surfaces confermato ancora aperto):**
  `token_registry.json` porta ancora `flatFee=0.60` / `aboveFee=3.00` USDC (mainnet 1/8453
  **e** Base Sepolia 84532). Per design le fee keys valgono solo per il router v1; lo
  zero-fee diventa vero on-chain solo con il deploy di RSendsRouterV2 +
  `RSENDS_ROUTER_V2_ADDRESSES_JSON` (operator-out, piano P3/PR #73). **Oggi, sulla rete
  attiva (Base Sepolia), i pagamenti passano ancora dal router v1 con fee** — coerente col
  piano, ma il claim "zero fee" del sito resta forward-looking fino al cutover.

## 4. Igiene repo

- Nessun dump prod tracciato (`git ls-files | grep dump` → vuoto); in git solo
  `.env.example` / `.env.production.example`; gitignore corretto. Il rischio dump flaggato
  il 2026-07-20 risulta rientrato.
- `main` locale era 11 commit indietro (fetch fatto in sessione); il branch corrente
  `fix/silent-login-errors` è interamente contenuto in origin/main (PR #74 merged) → si può
  tornare su main e cancellarlo.
- ~70 branch locali già merged (rumore, `git branch --merged origin/main` per la lista).
- Untracked in root: questo report + `login-failure-discovery-2026-07-24.md` +
  `ponytail-review-preview-2026-07-22.md` (pattern consolidato, ok).

## 5. Prod runtime osservato

- `GET /health` → `healthy`, `redis: connected`, `idempotency: active`, indexer 84532:
  `last_block 44616984, lag 0, stalled false, finality_degraded false`.
- Frontend (Vercel `r-sends-non-custodial-web`, domini `pay.rsends.io` / `demo.rsends.io`):
  `/pay` 200, `/` → 307 `/docs`, `/en/app` → 307 login (gate sessione attivo), login 200.
  Ultimo deploy production READY del 2026-07-24 12:41 (= merge #74 incluso).
- **Render MCP: unauthorized** (`list_workspaces` → unauthorized; conferma la memoria del
  24/07). Non verificabili direttamente: env vars del backend (ADMIN_API_TOKEN,
  ENVIRONMENT=production, INDEXER_USE_FINALIZED_TAG, RSENDS_ROUTER_V2/SPLIT_ROUTER
  ADDRESSES_JSON, INTERNAL_PROXY_SECRET) e i log (resta pendente la query sul codice del
  401 di login in prod, dal report login-failure). Per riattivare: ri-autenticare il
  server Render via `/mcp` in una sessione interattiva.

### Stato env (confermato / inferito / non verificabile)

| Item | Stato |
|---|---|
| Redis provisionato + connesso | **Confermato** (health) |
| DEBUG=false | **Inferito forte** (/docs 404) |
| ADMIN_API_TOKEN impostato | **Inferito** (403 con token errato; approvals via curl funzionavano il 14/07) |
| ENVIRONMENT=production | Non verificabile (nessun effetto osservabile dall'esterno) |
| INDEXER_USE_FINALIZED_TAG=false (fix A, PR #44) | Non verificabile; lag 0 suggerisce indexer sano comunque |
| RSENDS_ROUTER_V2_ADDRESSES_JSON | **Non impostato per design** (cutover mainnet futuro) |
| SPLIT_ROUTER_ADDRESSES_JSON | Non verificabile (deploy split PR #45 era pending) |
| INTERNAL_PROXY_SECRET | Operator-out post-deploy (piano P3), non verificabile |

## 6. Follow-up classificati

**Blocker operativi immediati (pre qualunque altra cosa):**
1. Billing GitHub Actions (CI morta, §1).
2. Ri-autenticare Render MCP se si vuole osservabilità operativa da queste sessioni.

**Blocker per il go-live mainnet (non per lo stato attuale testnet):**
- Deploy RSendsRouterV2 + env cutover (`RSENDS_ROUTER_V2_ADDRESSES_JSON`) — finché non
  avviene, "zero fee" è solo copy e "live" env è inutilizzabile.
- `/app` è hard-locked a `test`: nessuna UI su dati live finché non esiste l'env toggle
  (gap accettato al ritiro del merchant dashboard).
- Redis-DOWN/degraded path senza copertura test (fail-closed è security-relevant; pass
  dedicato).
- Org_id re-key residuo: `payment_intents`/`merchant_webhooks` ancora tenant-keyed
  sull'indirizzo wallet (~16 siti; api_keys slice DONE con 0014). Interim sicuro
  (fallback 2026-07-12) ma con identity-flip e griefing DoS-not-leak noti.

**Decisioni operatore pendenti (non di codice):**
- Utenti pure-OAuth lockati fuori dal 2026-07-13 (query conteggio nel body di PR #25).
- Fate delle chiavi `rsusr_` (autenticano zero route).
- Alembic: drift→stamp head su prod (PR #18, lato operatore).
- Cleanup env OAuth su Render/Vercel.
- Query log Render per il codice esatto del 401 login prod (login-failure report).

**Post-launch accettati / batch dedicati (dal CLAUDE.md, non toccare drive-by):**
- Residui custodial dormienti backend (router `user_transactions`/`user_contacts`/
  `user_routes` registrati ma caller-less; `merchant_profiles`; `blacklisted_wallets`;
  `EXEMPT_PATHS` morti; root `app/page.tsx`).
- Envelope errori incoerente (flat vs `{detail:{}}` — visto anche nel 422 dei probe).
- Ritiro `/api/v1/keys/*` wallet-sig + `dashboard_routes.py` (post-Manimama).

## 7. Delta piano P0–P5 (DONE-dichiarato vs DONE-verificato)

| Fase | Dichiarato | Verificato oggi |
|---|---|---|
| P0 concurrency (#58) | merged | ✓ merged; test concurrency PG inclusi nei 768 |
| Fail-loud triage (#64/65/66) | merged | ✓ merged; topic-hash pin passa |
| P3 router v2 (#73) | merged, no deploy | ✓ merged; 86/86 contracts; deploy = operator-out |
| Login silent-failure (#74) | merged | ✓ merged e già in prod (deploy 12:41 del 24/07) — ma mai passato dalla CI |
| P1 triage findings | non iniziato | invariato |
| P2 copy pricing split | — | non valutato in questo audit |
| P4 /pay hardening, P5 i18n | non iniziati | invariato |

---
*Metodo: probe HTTP read-only su prod, suite locali complete (PG+Redis reali), grep/lettura
codice su origin/main f5390379, gh CLI per CI/PR, Vercel MCP (Render MCP unauthorized).*
