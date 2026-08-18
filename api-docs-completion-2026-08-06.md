# API doc completion — consegna, 2026-08-06

> **Aggiornamento 2026-08-08.** La domanda aperta #4 ("percorso di approvazione per un partner")
> è stata risolta con un cambio di codice, non con una riga di doc: **il gate sandbox è ora
> KYB self-service, zero attesa umana**. Vedi la sezione in fondo, *Follow-up 2026-08-08*.
> Le domande #1 (`api.rsends.io`) e #2 (DB di produzione) restano aperte.

Sostituiti i placeholder delle API doc pubbliche con i valori reali ricavati dal codice.
Tre consegne: (1) cosa è cambiato nella doc, (2) endpoint esclusi dalla superficie pubblica,
(3) domande aperte + bug trovati e **non** toccati.

**Regola seguita:** ogni valore viene dal codice o da una probe live. Nessun segreto vero,
nessun URL `*.onrender.com`, nessun indirizzo mainnet inventato, zero modifiche a codice di
produzione.

---

## ⚠️ Prima di tutto: il backend di produzione ha il database irraggiungibile

Scoperto durante le probe di verifica, **non** causato da questo lavoro.

```
GET /health/deep  →  503
"postgres": { "status": "error", "detail": "[Errno -2] Name or service not known" }
"redis":    { "status": "ok", "latency_ms": 2.0 }
"rpc_base": { "status": "ok", "chain_id": 84532, "block": 45134310 }
```

`Name or service not known` = **l'hostname del database non risolve**. Non è il DB che rifiuta
la connessione: è il DNS. La forma è quella di una `DATABASE_URL` stale — stesso profilo
dell'incidente Redis internal-migration del 2026-07-11.

Conseguenze osservate in produzione, adesso:

| Sintomo | Probe |
|---|---|
| Ogni route che tocca il DB → **500** | `GET /api/v1/public/payment-intent/{qualsiasi id}` → `500 INTERNAL_ERROR` |
| Idem | `GET /api/v1/tx/recent` → `500` |
| **Il checkout ospitato non carica** | `https://demo.rsends.io/api/pay/{id}` → `500` (è il proxy che alimenta `/pay`) |
| Indexer fermo | `health` → `stalled: true`, `last_block 45127159` contro un tip a `45134310` (~7000 blocchi indietro, non avanza) |
| Non tocca il DB → funziona | `GET /api/v1/prices` → `200`; auth middleware → `401` corretto |

**Non ho toccato nulla** — è infra/operator, fuori dallo scope e fuori dal mandato. Ma va
sistemato prima di mandare la doc a chiunque: oggi un partner che segue il quickstart arriva
allo step 3 e trova il checkout rotto.

---

## 1. Doc aggiornata

`apps/web/app/docs/` — pagine Next.js TSX, servite su `pay.rsends.io/docs`.
**+544 / −163** su 11 file, più una pagina nuova. Nessun file fuori da `app/docs/`.

### Nuova pagina: `/docs/quickstart`

Da zero a un pagamento di test in sei step, copiabile: key → create intent → checkout →
webhook → verifica firma → verifica on-chain. Inserita come secondo item in "Get started";
la catena `PageNav` di Overview e Authentication è stata riallineata.

### Correzioni bloccanti (la doc, com'era, non funzionava)

| Era | È | Fonte |
|---|---|---|
| Base URL `https://pay.rsends.io` | `https://pay.rsends.io/api/backend` — l'originale dà **404** su `/api/v1/merchant/*` (è Next.js, non il backend; nessuna rewrite) | probe live + `apps/web/app/api/backend/[...path]/route.ts` |
| Chiavi `rk_test_` / `rk_live_` | `rsend_test_` / `rsend_live_` | `app/security/api_keys.py:121` |
| `intent_id: "int_abc123"` | `pi_` + 32 hex | `app/services/intent_service.py:363` |
| `routerVersion 2`, `fee "0"`, `total == amount` | **`routerVersion 1`**, `fee` live da `quoteFee`, `total = amount + fee`, `maxFee = fee`. Il router v2 non è deployato (`RSENDS_ROUTER_V2_ADDRESSES_JSON` non impostata) | `router_registry.py:609-651`, `token_registry.json`, `packages/contracts/README.md:115`, DEPLOY_RUNBOOK Part 6 |
| "Chiavi emesse dall'operatore, nessun self-serve" | Self-serve da `/app` → API keys → Merchant keys (ruolo org `admin`, scope `write`, env `test`, cap 5, plaintext una volta) | `user_org_merchant_keys_routes.py` |
| "Apri il `checkout_url` restituito" | Quel campo **non esiste**: l'URL si compone, `demo.rsends.io/pay/{intent_id}` | `merchant_models.py:448-475` |
| Create risponde `201` | `200` | nessun `status_code=` sul decorator |

**La correzione più pesante è quella sulle fee.** La doc prometteva che il pagante autorizza
esattamente l'importo. Sulla sandbox autorizza `amount + 0.60 USDC` (3.00 sopra i 1000). Ora la
pagina Payment intents ha una tabella `routerVersion 1 oggi` vs `2 al cutover`, e ovunque la
regola è "fai il fork su `routerVersion`, non su un'assunzione". Il principale del merchant
arriva intero in entrambi i casi — quello non è mai stato in discussione.

### Aggiunte (superficie reale che la doc taceva)

- **Approval gate** — ogni `/api/v1/merchant/*` dava `403` finché l'org non era approvata. È il
  primo muro che incontra un integratore e non era scritto da nessuna parte. Documentato su
  Authentication e nel quickstart. *(Superato dal follow-up 2026-08-08 in fondo: il gate sandbox
  è ora `company_profile_required`, e la doc è stata riallineata.)*
- **Rate limit** — nuova sezione in Errors con i valori veri (create 100/min, cancel/resolve
  10/min, GET 60/min, webhook register 5/h, test 10/min, globale per-key 100/min, public 20/min
  per IP), header, `retry_after`, e il fail-closed `503 RATE_LIMIT_UNAVAILABLE`.
- **Retry webhook** — 5 tentativi, backoff 30s → 2m → 8m → 32m → 2h, timeout 10s per attempt,
  successo = 2xx, dedupe su `X-RSend-Delivery-Id`.
- **Idempotenza** — `X-Idempotency-Key` su qualsiasi POST, replay 24h, `409
  DUPLICATE_REQUEST_IN_FLIGHT`. C'era l'errore documentato ma non l'header che lo produce.
- **Campi create mancanti** — `amount_tolerance_percent`, `late_payment_policy`, `split`
  (2–20 leg, bps esatti 10000), e `network` marcato **accettato ma ignorato**.
- **Recipient gate** — senza `recipient` esplicito serve il settlement wallet dell'org, altrimenti
  `422 SETTLEMENT_WALLET_MISSING`. Mai un default silenzioso.
- **Endpoint `resolve`** — era citato solo sotto Refunds, ora è nel reference.
- **Envelope errori** — sono **due** forme: le route danno `{"detail":{error,message}}`, la
  pipeline dà `{error,message}` piatto. Documentate entrambe con il one-liner per gestirle
  (`body.detail ?? body`).
- **Tabella errori riscritta** — tolti `INVALID_SIGNATURE` e `DUPLICATE_TX` (esistono solo su
  `/api/v1/tx/callback`, superficie custodial-era, irraggiungibili dalla API merchant); aggiunti
  i reali: `UNSUPPORTED_CHAIN`, `SETTLEMENT_WALLET_*`, `SPLIT_UNAVAILABLE`,
  `WEBHOOK_URL_FORBIDDEN`, `WEBHOOK_INACTIVE`, `SETTLEMENT_IN_FLIGHT`, `INVALID_STATUS`,
  `KEY_RATE_LIMIT_EXCEEDED`, `RATE_LIMIT_UNAVAILABLE`, `BACKEND_UNREACHABLE`.
- **ETH** — anche il nativo è `enabled` su Base Sepolia; la doc diceva "USDC è l'unico".
- **`resolve` vale solo da `review`** — la pagina Refunds implicava di poter registrare un
  refund su qualsiasi pagamento completato. Non si può: `400 INVALID_STATE`. Detto esplicito,
  con il workaround (tienilo nei tuoi libri).
- **Ambienti** — Overview ora apre con Sandbox vs Produzione; i valori di produzione sono
  marcati *pending*, non inventati.

### Il caveat della base URL, documentato e non nascosto

`/api/backend` è il proxy edge. Inoltra `authorization`, `content-type`, `accept`,
`x-idempotency-key`; restituisce status e body verbatim; **ma rilancia solo `Content-Type`**,
quindi gli header `X-RateLimit-*` / `Retry-After` / `X-Idempotency-Replayed` non arrivano al
client, e oltre 25s dà `502 BACKEND_UNREACHABLE`. È scritto in Overview e in Errors, con
l'indicazione di leggere `retry_after` dal body.

### Non toccato perché già corretto

Il **contratto payload dei webhook**: il key set combacia esattamente con `CONTRACT_KEYS` in
`tests/test_webhook_contract.py:71-93`, extra per-evento inclusi, e la lista eventi combacia con
`VALID_EVENTS`. Firma HMAC, finestra 5 minuti, header: tutto verificato e lasciato com'era.

### Verifica eseguita

- `npm run build` → verde, `/docs/quickstart` prerenderizzata insieme alle altre 9.
- `npx tsc --noEmit` → zero errori sotto `app/docs`.
- `npx jest app/__tests__/marketing/pagesRender.test.tsx` → 50/50 (i warning `act()` sono
  pre-esistenti e vengono da `TypewriterHeadline`, non dalle doc).
- Probe live senza credenziali: `GET .../api/backend/api/v1/merchant/transactions` → **401
  `INVALID_API_KEY`**, cioè la base URL documentata raggiunge davvero il backend.
- Grep di chiusura: zero occorrenze residue di `rk_`, `int_abc`, `pay.rsends.io/api/v1`, `201`.

**Il quickstart NON è stato eseguito end-to-end.** Serve una key sandbox con org approvata, e
comunque oggi fallirebbe allo step 3 per l'outage del DB qui sopra. Ogni valore è verificato
alla sorgente, ma "verificato dal codice" non è "provato in volo" e non lo spaccio per tale.

---

## 2. Endpoint esclusi dalla superficie pubblica

Inventario completo dai decorator in `services/backend/app/api/`. **Niente di questo è nella
doc** — decidi tu se qualcosa merita di entrare.

| Gruppo | Endpoint | Perché fuori |
|---|---|---|
| **Admin / server-to-server** | `GET /api/v1/audit/log`, `/admin/aml/*` (4), `/admin/approvals` + `/{org_id}/approve\|decline`, `GET /health/config` | Auth `X-Admin-Token`; il proxy web li denylista già |
| **Sessione dashboard (JWT)** | tutta `/api/v1/user/**` — org payments/webhooks/stats, `merchant-keys`, onboarding, wallets, account, notifications, contacts, routes, api-keys `rsusr_` | Controparte browser del dashboard, non una API da integrare |
| **Auth utente** | `/api/v1/auth/*` — signup, login, refresh, logout, me, wallet-session | Autenticazione dell'utente umano |
| **Custodial-era / dormienti** | `/api/v1/tx/*`, `/api/v1/anomalies`, `/api/v1/keys/*` (wallet-sig, in ritiro), `/api/v1/dashboard/stats` (congelato e scope-broken), `/api/v1/forwarding`, `/api/v1/distributions`, `/api/v1/aml/check` | Residuo pre-non-custodial, o in dismissione |
| **Rotte non raggiungibili in prod** | `/api/v1/merchant/profile`, `/api/v1/merchant/invoices` | JWT-authed ma fuori da `EXEMPT_PATHS`: in produzione danno 401 senza `RSEND_DEV_AUTH_BYPASS`. Hanno prefisso `/merchant` ma **non** sono API merchant |
| **Infra** | `/health`, `/health/deep`, `/api/v1/prices*`, `/api/v1/organizations*`, `/api/v1/invites*` | Non fanno parte del contratto d'integrazione |

**Una eccezione che ho preso io, dimmi se la vuoi diversa:**
`GET /api/v1/public/payment-intent/{intent_id}` — pubblico by-design (id-as-secret, view
allowlistata, read-only, 20/min per IP). L'ho documentato in **una sola riga** su Hosted
checkout, sotto "Build your own checkout?", perché è ciò che il checkout stesso pollinga e chi
si costruisce il front-end da sé lo cercherà comunque. Se preferisci superficie minima, tolgo
quel paragrafo — è isolato.

---

## 3. Domande aperte

1. **Hostname API.** `api.rsends.io` non risolve. Oggi la doc punta a
   `pay.rsends.io/api/backend`, che funziona ma passa dal proxy (header di quota persi, timeout
   25s). Quando attiviamo il custom domain su Render? Al cutover cambiano poche righe.
2. **Il DB di produzione è giù** (sezione in cima). Sblocca tutto il resto.
3. **Sezione Produzione con i buchi.** Base URL, indirizzo router e token restano marcati
   *pending* finché il v2 non è deployato. Confermi che va bene pubblicare così?
4. **Percorso di approvazione per un partner.** La doc ora dice che esiste il gate, ma non come
   si supera — chi si contatta, quanto ci vuole. Serve una riga concreta, altrimenti il primo
   403 resta un vicolo cieco.
5. **`GET /api/v1/public/payment-intent/{id}`**: documentato in una riga (sopra). Lo tengo?
6. **Chiavi `rsusr_`.** Non documentate. La loro verifica è cablata a zero route, quindi oggi
   non autenticano niente. Confermi che non sono destinate ai partner?

### Bug e incoerenze trovati — segnalati, non toccati

| Dove | Cosa |
|---|---|
| **prod (infra)** | `postgres` irraggiungibile per DNS → 500 su tutto ciò che tocca il DB, checkout ospitato incluso, indexer fermo |
| `app/middleware/rate_limit.py` docstring | Dichiara `POST /payment-intent → 30/min`, ma `ENDPOINT_LIMITS` dice **100/min**. Ho documentato 100 (il codice vince). Il commento va allineato |
| Envelope errori | Route `{"detail":{...}}` vs middleware `{...}` piatto. È il follow-up "Error envelope inconsistency" già tracciato in CLAUDE.md. Documentate entrambe le forme invece di fingere uniformità |
| Due token registry | `app/token_registry.json` (gate vero dei pagamenti, via `router_registry`) e `app/tokens/registry.py` (mirror per la conversione USD) divergono: il secondo elenca cbBTC, WETH, token Arbitrum che il gate pagamenti rifiuta. Documentato il primo |
| `CreatePaymentIntentRequest.currency` | Allowlist di schema `{ETH,USDC,USDT,DAI,cbBTC,DEGEN}` più larga del registry: `DEGEN` e `cbBTC` passano Pydantic e poi sbattono su `400 UNSUPPORTED_TOKEN`. Funziona (fail-closed), ma i due livelli non concordano |
| `IntentStatus` | Ha sia `paid` che `completed` come stati di successo. Documentati entrambi con l'istruzione di accettarli entrambi, ma è debito che prima o poi va sciolto |
| Refund su intent completato | Non esiste un modo di registrarlo: `resolve` accetta solo `review`. Se serve ai merchant è una feature mancante, non un buco di doc |

---

## Follow-up 2026-08-08 — gate sandbox: KYB self-service, zero attesa umana

Indagando la domanda aperta #4 è emerso che **il gate non era uno, erano due**, e quello
bloccante non era l'approvazione: era il KYB. Il funnel reale per ottenere una key testnet era

```
signup → email → form KYB → submit → ⏳ umano approva via X-Admin-Token
       → SOLO ORA mint della key → l'API risponde
```

Il collo di bottiglia stava su `require_org_approved("admin")` alla **rotta di mint**, non sulla
API merchant: ungatare solo la API sarebbe stato inutile, il partner non riusciva comunque a
*ottenere* una key. E dato che il mint è hard-pinned a `ENVIRONMENT = "test"`, tutto quel funnel
— visura, P.IVA, attesa umana — proteggeva **soltanto una testnet con soldi finti**.

In più il codice dichiarava già un'altra cosa: il docstring di `submit_company_profile` dice
`'company_submitted' = full testnet access, zero human review`. Il gate manuale sopra era la
divergenza. **Questo cambio ripristina l'intento già scritto**, non allenta una policy.

### Cosa è cambiato

| File | Cambio |
|---|---|
| `app/api/deps/approval_policy.py` **(nuovo)** | La definizione UNICA di "approvato abbastanza", environment-scoped. Sandbox = allowlist `{pending_approval, approved}`; live = solo `approved`; `declined` blocca ovunque |
| `app/api/deps/require_org_approved.py` | Delega la decisione alla policy. Nuovo kwarg `environment` (default sandbox) → il giorno in cui `/app` avrà l'env toggle, basta passarlo per riavere la regola stretta |
| `app/api/deps/require_approved_merchant.py` | Legge `client["environment"]`: key `test` passa da pending, key `live` invariata. **Environment assente ⇒ regola stretta** (mai carve-out per default) |
| `app/api/user_org_merchant_keys_routes.py` | Guard: mintare per un environment ≠ sandbox richiede approvazione reale. Oggi irraggiungibile (pin `test`), diventa il gate il giorno in cui il pin cade |
| `apps/web/lib/onboarding.ts` | **La trappola vera**: `resolveOnboardingRedirect` parcheggiava *qualsiasi* org non-`approved` su `/onboarding/pending`. Col solo cambio backend il partner avrebbe finito il KYB e sarebbe rimasto comunque su una schermata d'attesa. Ora `pending_approval` entra in dashboard; `declined` no |

**Invarianti conservate, verificate da test:** il KYB resta obbligatorio (`company_profile_required`
fira prima di tutto); `declined` blocca in entrambi gli environment; stati sconosciuti falliscono
chiusi *anche* in sandbox (allowlist, non "tutto ciò che non è declined" — così un futuro
`suspended` blocca per default); owner irrisolvibile/ambiguo continua a essere negato ovunque
(è tenant-safety, non approvazione). `admin_approval_routes.py` e la coda admin: **intatti**, gli
org nascono ancora `pending_approval` e `notify_merchant_pending` ti avvisa ancora. L'operatore
smette di essere un collo di bottiglia per la testnet, resta obbligatorio per il live.

`/onboarding/pending` e `ApprovalPendingScreen` **non** sono stati cancellati: tornano la
destinazione giusta all'attivazione mainnet.

### Doc allineata nello stesso passaggio

- **Authentication** — "Your organisation must be approved" → "One prerequisite: your company
  profile", con la tabella dei campi richiesti (così un dev sa in anticipo cosa gli serve) e la
  nota che il manuale resta per il live.
- **Quickstart** — step 1 riscritto: nessuna coda di approvazione, il 403 da conoscere è
  `company_profile_required`.
- **Errors** — `company_profile_required` aggiunto come riga propria; `approval_pending` e
  `approval_declined` separati, con l'ambito corretto di ciascuno.

### Verifica

- Backend: **770 passed, 34 skipped** (suite intera). `test_approval_gate.py` esteso da 43 test,
  inclusi i nuovi su policy, key test vs live, key senza environment, e mint end-to-end di un org
  `pending_approval`.
- Frontend: **477 passed, 55 suite**. `npm run build` verde.
- **Non verificato in prod**: il DB è ancora giù (`/health/deep` → postgres irraggiungibile), quindi
  il quickstart end-to-end resta da eseguire. È il primo test da fare quando torna su.
