# Production-readiness delta audit — 2026-07-27

Delta audit read-only rispetto al report del 2026-07-25 (`production-readiness-2026-07-25.md`).
Ogni claim del report precedente è stato ritrattato come ipotesi e ri-verificato; dove non
regge più, è detto esplicitamente. Ogni riga porta il comando/probe/file:linea che l'ha
prodotta ed è classificata **Verificato** (comando eseguito, output visto), **Inferito**
(catena esplicitata) o **Non verificabile** (con l'accesso mancante).

**Baseline: main @ `0ad08e17`** (merge PR #75, 2026-07-27 14:35 CEST), **verificato dalla CI
GitHub con il run push-triggered `30266506614`, tutti e 4 i job verdi** (Contracts 31s,
E2E Anvil 1m10s, Backend 3m25s, Frontend 4m34s — `gh run watch` in sessione). Il tree locale
su cui girano le suite è `main` fast-forwardato allo stesso sha (working tree pulito salvo il
noto `M .claude/settings.json`, accrescimento benigno di permessi tool, e i report untracked).

## Verdetto sintetico

| Area | Stato | Nota |
|---|---|---|
| Codice / suite di test | 🟢 | backend 768/26/**0** (72s, PG+Redis reali); contracts 86/86; `npm run build` exit 0; jest 476/476; **E2E Anvil eseguito in locale: 6/6 in 5.3s** |
| CI GitHub | 🟢 | billing risolto (sbloccato tra le 10:08 e le 12:29 UTC di oggi); il tip di main è CI-verificato (run 30266506614) |
| Gate strutturale della pipeline | 🔴 | la CI è **advisory**: branch protection impossibile sul piano attuale (`gh api …/protection` → 403 "Upgrade to GitHub Pro"), e Vercel ha creato il deploy production **3 secondi dopo il push**, a CI ancora in corso |
| Invarianti di sicurezza | 🟢 | ri-derivate da zero su codice + probe prod: recipient gate 2 hit conformi + zero path grep-blind, rate-limit fail-closed, tenancy, auth |
| Prod runtime (osservabile) | 🟢 | `/health` healthy, Redis connected, indexer 84532 lag 0, stalled false |
| Env/config Render | 🟡 | **Render MCP ancora unauthorized** — dashboard non ispezionabile; blueprint `render.yaml` letto come proxy documentale |
| Mainnet go-live | 🔴 | per design, invariato: router v2 non deployato, `/app` test-locked, fee v1 attive on-chain |

**In sintesi:** i due blocker operativi del 25/07 (billing CI, main mai verificato) sono
chiusi. Il quadro codice è il più solido mai osservato: per la prima volta il money-path E2E
è stato eseguito sia in CI (due volte oggi, verde) sia in locale (6/6). Ciò che resta è
quasi tutto operator/terze-parti per il mainnet, più un gap strutturale di processo: **oggi
un commit su main raggiunge comunque la produzione senza aspettare alcuna verifica
automatica** — la CI verde è correlazione, non gate.

---

## 1. Correzioni ai report precedenti (dovute, non cosmetiche)

- **"L'E2E Anvil non era mai girato da nessuna parte" — FALSO** (era nel brief del task, e
  io stesso l'ho ripetuto nel Phase 0-bis come "prima volta oggi"). Verificato: il run
  `30093563795` (branch di PR #74, 2026-07-24) **includeva il job E2E (Anvil money-path),
  verde in 1m11s** (`gh run view 30093563795`), e il job esiste in `ci.yml` almeno dal
  2026-07-14 (`git log -- .github/workflows/ci.yml`: dea88f03 "bound the E2E job"). Il gap
  reale era duplice e più stretto: (a) nessun run è mai girato sui **merge commit** di main
  durante il blocco billing (24–27/07); (b) l'audit del 25/07 non l'aveva eseguito
  **localmente**. Entrambi chiusi oggi.
- **"Codice verificato localmente al 100%" (25/07)** — andava qualificato: la suite piena
  locale e il job CI Backend non selezionano lo stesso insieme (v. §2). La differenza è
  ora quantificata ed è benigna, ma il numero 768 e il verde CI non erano confrontabili
  senza questa analisi.

## 2. CI: cosa copre davvero il verde (delta per marker) — Verificato

Il job Backend gira `pytest -q -m "not e2e and not integration"` (`ci.yml:92`). Conteggi
sullo stesso contenuto (`0ad08e17`):

- Collection locale piena: **794 test**; selezione CI-equivalente: **784** (10 deselezionati:
  `--collect-only -q -m "e2e or integration"`).
- **6 marcati `e2e`** — tutti in `tests/e2e/` (money-path v1 e v2: permit-loop, approve+pay,
  negativo short-amount). **Coperti dal job E2E dedicato** (`make e2e-anvil` →
  `pytest -m e2e tests/e2e`, Makefile:82-86). Nessun buco.
- **4 marcati `integration`** — tutti in `tests/test_api.py:177-213`: i read legacy
  compliance `/api/v1/tx/{ref}` e `/api/v1/anomalies` (residuo custodial), **doppiamente
  quarantenati** (skip esplicito + marker) perché dietro deny-by-default auth dal 2026-07;
  il commento in-file: "Un-skip by building the authenticated fixture". **Coperti da NESSUN
  job**, ma non sono money-path né asserzioni di sicurezza attive: asseriscono il
  comportamento *pre*-hardening. Non è un buco del gate; è residuo tracciato.
- **Riconciliazione conteggi CI vs locale**: CI = 772 passed + 12 skipped (+4 deselected)
  = 784 selezionati, identico al locale; il log CI (`gh run view --job 89978354366 --log`)
  chiude con `772 passed, 12 skipped, 4 deselected in 127.11s`. I 4 passed in più della CI
  rispetto al locale (768) sono i 4 test Alembic-Postgres che localmente skippano senza
  `ALEMBIC_TEST_DATABASE_URL` (CI la setta). **Nessun test viene ingoiato.**
- **Annotazione `Event loop is closed`** sul job Backend verde: presente anche sul run di
  PR #74 (quindi pre-esistente, non introdotta da #75). Con i conteggi che tornano al
  test-singolo, è **rumore di teardown**, archiviato con questa riga — ma un'annotazione
  error-level su job verde va prima o poi silenziata, perché insegna a non guardare le
  annotazioni (item in coda).
- **onchain-verify**: i 3 failure 25–27/07 (incl. run 30256826944 di stamattina 10:08 UTC)
  portano tutti l'annotation billing letterale = **artefatti pre-sblocco, non regressioni**
  (nessuno step è mai partito, 4s). Ultimo run realmente eseguito: 2026-07-24 08:41,
  success. Il dispatch manuale annunciato dall'operatore **non risulta ancora alle 12:56
  UTC** (`gh run list --workflow=onchain-verify.yml`); prossimo cron 06:17 UTC di domani.

## 3. Suite locali — tutte e quattro le superfici della matrice CI (Verificato)

Ambiente: Redis PONG, Postgres 5432 up, anvil/forge presenti, web3 7.16.0 nel venv.

- **Backend** (`./venv/bin/python -m pytest -q` + `CONCURRENCY_TEST_DATABASE_URL`):
  **768 passed, 26 skipped, 0 failed in 72.06s**. Skip interamente decomposti (`-rs`):
  7 `test_merchant_flow_e2e` (vuole un backend live su :8000 — coperto da nulla in CI, è
  flow legacy con auth bypass), 6 e2e (girati a parte, sotto), 4 Alembic-PG (verdi in CI),
  **4 circuit-breaker "pending rewrite" — incluso il path Redis-down/in-memory fallback:
  il gap di copertura fail-closed noto è CONFERMATO ancora aperto**
  (`test_circuit_breaker.py:337-395`), 4 quarantena custodial, 1 obsoleto HMAC. Nessuno
  skip nasconde asserzioni money-path. Cosmetico: una riga di skip mostra ancora il
  vecchio path `Desktop/wallet-connect/…` (residuo venv del repo spostato).
- **Contracts**: `forge test` → **86/86** su 4 suite (SetFeeConfig 6, RouterV2 23,
  SplitRouter 23, Router v1 34).
- **Web**: `npm run build` → **exit 0**; `npx jest --ci` → **476/476** (55 suite).
- **E2E Anvil money-path, eseguito in locale** (stessa invocazione del job, venv):
  **6 passed in 5.28s** — v1 e v2: `usdc_paywithpermit_full_loop`,
  `usdt_approve_pay_full_loop`, `short_amount_rejected_no_webhook` (+ le tre varianti v2
  single-transfer). Il money-path è verificato end-to-end sia in CI sia in locale, oggi,
  su questo contenuto.

## 4. Invarianti di sicurezza — ri-derivate da zero (Verificato salvo nota)

- **Recipient gate**: `grep -rn "PaymentIntent(" services/backend/app | grep -v "class
  PaymentIntent"` → esattamente i **2 hit** che il CLAUDE.md post-#75 dichiara
  (`intent_service.py:408` persistito, `webhook_service.py:1279` sintetico). Doc e realtà
  ora coincidono verbatim. Caccia ai path invisibili al grep: `insert(PaymentIntent`,
  `bulk_insert_mappings`, `bulk_save_objects`, insert Core su `payment_intents`,
  `execute(` con riferimenti agli intent → **zero hit**; `db.add(intent)` esiste solo in
  `intent_service.py:428`, a valle del gate; `_build_test_event_payload(webhook)` non ha
  handle db (webhook_service.py:1271).
- **Rate limiting**: `ENDPOINT_LIMITS` esplicita (rate_limit.py:53+, most-specific-first),
  route non elencate → `DEFAULT_GET_LIMIT`/`DEFAULT_POST_LIMIT` per-IP (rate_limit.py:429-433);
  Redis giù + `debug=false` → **503 RATE_LIMIT_UNAVAILABLE** (rate_limit.py:445-454,
  commento F-BE-10). In prod: il probe pubblico risponde con `x-ratelimit-limit: 20`.
- **Tenant isolation**: i 5 pin cross-org esistono e sono dentro i 768 verdi
  (`test_user_org_payments.py::test_cross_org_isolation_no_leak`,
  `test_user_org_intent_create.py::test_session_create_isolation`,
  `test_webhook_reads.py::test_list_org_isolation` + `::test_deliveries_cross_tenant_404`,
  `test_org_stats_usd.py::test_stats_org_isolation_no_leak`). Residuo org_id re-key:
  `resolve_owner_address` conta **22 righe di call-site in 6 moduli di route** (grep in
  sessione; il CLAUDE.md dice ~16 siti — l'ordine di grandezza regge, la stima va
  aggiornata al prossimo pass dedicato). `payment_intents`/`merchant_webhooks` restano
  tenant-keyed sull'indirizzo wallet.
- **Auth fail-closed**: `_get_merchant_id` 401 senza client (merchant_routes.py:80-88);
  `require_admin` constant-time, nega tutto se il token non è configurato
  (audit_routes.py:49-59).
- **Probe HTTP read-only su prod** (tutti Verificati):
  `GET /api/v1/merchant/transactions` senza auth → **401**; public intent inesistente →
  **404 + header rate-limit**; `/health/config` e `/admin/approvals` senza header → **422**
  (validazione FastAPI, nessun leak); `/admin/approvals` con token errato → **403**;
  `/docs` e `/openapi.json` → **404** ⇒ DEBUG=false (Inferito forte, stessa catena del
  25/07). Nota di percorso: `/api/v1/admin/approvals` (path inesistente) → 401 dal
  middleware API-key — anche i path ignoti falliscono chiusi.

## 5. Prod runtime e ambiente

- `GET /health` → `healthy`, `redis: connected`, `idempotency: active`, indexer 84532:
  `last_block 44694206, lag 0, stalled false, finality_degraded false` (Verificato).
- Frontend: `/pay` 200; `/` → 307 `/docs`; `/en/app` → 307 login con redirect param;
  `/en/login` 200; `demo.rsends.io` → 307 `/en` (Verificato).
- **Vercel**: progetto `r-sends-non-custodial-web`, ultimo deployment production
  `dpl_4HsWWRGjWZEHfbAWdsZHNizByM9D` **creato alle 12:35:08.586 UTC** = 3 secondi dopo il
  push del merge #75 (12:35:05), `readyState: READY` (Verificato via Vercel MCP).
- **Render MCP: unauthorized** anche oggi (`list_workspaces`). Non verificabili: env var
  reali del backend e i log — la query sul codice esatto del 401 di login prod
  (login-failure report) **resta irrisolvibile da questa sessione**; serve ri-autenticare
  il server Render via `/mcp` in una sessione interattiva.

### Stato env (ricostruito da zero, non copiato)

| Item | Stato |
|---|---|
| Redis provisionato + connesso | **Verificato** (health) |
| DEBUG=false | **Inferito forte** (/docs+openapi 404; render.yaml lo dichiara, ma il blueprint non prova il dashboard) |
| ADMIN_API_TOKEN impostato | **Inferito** (403 con token errato non distingue set/unset; il funzionamento delle approvals via curl del 14/07 sì) |
| ENVIRONMENT=production | Non verificabile direttamente (blueprint la dichiara) |
| INDEXER_USE_FINALIZED_TAG | Non verificabile; **nota**: il blueprint dice `"true"`, il fix A (PR #44) voleva `false` da dashboard — quale sia attivo non è osservabile da fuori; lag 0 non discrimina |
| RSENDS_ROUTER_V2_ADDRESSES_JSON | **Non impostata per design** (cutover futura); **assente anche dal blueprint `render.yaml`** → alla cutover va aggiunta a mano, non verrà dal blueprint |
| SPLIT_ROUTER_ADDRESSES_JSON | Non verificabile (nel blueprint come `sync: false`) |
| INTERNAL_PROXY_SECRET | Non verificabile (blueprint `generateValue`) |

## 6. Inventario gate mainnet (Pass 4)

- **RSendsRouterV2 deploy + cutover**: il lato codice è COMPLETO e pinnato — env var
  cablata (`config.py:62` `rsends_router_v2_addresses_json`, "the mainnet cutover is this
  one env var" nel commento; plumbing pinnato da `test_router_v2.py:363+`; "v2 wins when
  both configured" in `router_registry.py:575`); `DeployRouterV2.s.sol` e
  `AUDIT_HANDOFF_ROUTERV2.md` esistono. Sblocco: deploy contratto post-audit + una env var
  (operator). Attenzione blueprint (riga sopra).
- **`token_registry.json` fee keys v1**: ancora `flatFee=600000`/`aboveFee=3000000` su
  mainnet E Base Sepolia (Verificato). Il `_comment` ora documenta che le chain v2 le
  ignorano e NON vanno mai passate a `SetFeeConfig.s.sol`. Oggi, sulla rete attiva, i
  pagamenti passano dal v1 **con fee on-chain**: lo zero-fee resta forward-looking.
- **Direzione della fee — decisa dal sorgente v1, non dalla doc** (Verificato,
  `RSendsRouter.sol:72-73`):
  `IERC20(token).safeTransferFrom(msg.sender, merchant, amount);` poi
  `if (fee != 0) IERC20(token).safeTransferFrom(msg.sender, feeCollector, fee);`
  → **il payer manda amount + fee in due transfer separati; il merchant riceve l'importo
  PIENO; nulla viene dedotto dal settlement**. Conseguenza per Terms §6: la frase "nothing
  is deducted from on-chain settlements" è **on-chain accurata anche oggi**; a servire una
  revisione legale è **solo** la parte "fees are subscription-only" (esiste una protocol
  fee per-transazione, a carico del payer, finché gira il v1). Una frase, non il paragrafo.
- **Copy FAQ di PR #75** ("zero fee dal mainnet launch"): diventa falsa/da aggiornare alla
  cutover, e **nessun runbook la cattura** — grep su `DEPLOY_RUNBOOK.md` e
  `AUDIT_HANDOFF_ROUTERV2.md` per faq/copy/marketing/zero-fee: zero step. Gap: la sequenza
  di go-live non contiene il flip del copy.
- **`/app` hard-locked a `test`**: confermato nel codice (hook `useOrgPayments.ts:14,149`,
  `useOrgStats.ts:14` — nessun param `environment` inviato); nessun toggle. Invariato.
- **`/pay` fee disclosure**: confermato a livello codice —
  `SummarySection.tsx:6`: "No breakdown rows"; l'unica copy fee è
  `pay.summary.gasNote` ("Your wallet adds a small network gas fee on top"), che parla del
  gas e tace la protocol fee inclusa nel totale (`resolveFeeBreakdown` in
  `useHostedCheckout.ts:109`). Decisione operatore, poi eventualmente codice.
- **Redis-down/degraded**: ancora scoperto (Verificato, §3 — 4 skip "pending rewrite").
- **MiCA written opinion / RPagos audit**: gate di terzi, nessun artefatto nel repo da
  verificare; lo stato vive fuori da questa sessione (Non verificabile). Il pacchetto
  audit (`AUDIT_HANDOFF_ROUTERV2.md`, PR #73 congelata) è pronto lato repo.

## 7. Pipeline gating (Pass 5) — il punto strutturale

- **Sì: oggi un commit può raggiungere la produzione senza alcuna verifica automatica.**
  Evidenza diretta di oggi (Verificato): deployment Vercel production creato alle
  12:35:08, CI del tip conclusa ~12:40 — il deploy non aspetta i check. Per Render:
  Inferito (MCP unauthorized) — `render.yaml` non specifica `autoDeploy` (default: on) e
  il 24/07 il deploy coincise al secondo col merge; nessuna evidenza contraria.
- **La CI non può nemmeno diventare un merge-gate sul piano attuale**:
  `gh api repos/…/branches/main/protection` → **403 "Upgrade to GitHub Pro or make this
  repository public"** (Verificato) — branch protection/required checks non disponibili su
  repo privato free. Renderla vincolante = decisione operatore (Pro, o repo pubblico, o
  gating lato Vercel/Render tipo "Ignored Build Step"/deploy hook manuale).
- **Pattern minuti Actions** (diagnostico): `ci.yml` gira 4 job su ogni push a main e ogni
  push a ogni PR — nessun path filter, nessuna `concurrency` con cancel-in-progress; un
  giro completo costa ~10 minuti-runner (31s+1m10+3m25+4m34, ubuntu). `onchain-verify`:
  1 job/giorno + dispatch. Con il billing appena riattivato, ogni push su PR ribrucia
  l'intera matrice anche per diff docs-only (il run di #75, docs+copy, ha girato tutto).

## Chiusi dal 2026-07-25 (con l'evidenza che li chiude)

1. **Billing GitHub Actions** — runner attivi dalle ~12:29 UTC di oggi (re-run 30169615492
   eseguito per davvero, 5m03s).
2. **"Nessun run CI mai eseguito sul tip di main"** — chiuso da run `30266506614` su
   `0ad08e17`, 4/4 job verdi, osservato fino al completamento in sessione.
3. **E2E Anvil mai eseguito localmente** — chiuso: 6/6 in 5.28s in locale (§3), oltre ai
   due run CI odierni.
4. **Divergenza CLAUDE.md sul recipient gate** ("grep = one hit") — chiusa da `e644997d`
   (PR #75): grep e doc ora coincidono verbatim (§4).
5. **Zero-fee copy present-tense** — chiusa da `9d044457` (PR #75): claim condizionali
   "from mainnet launch" su 5 locale; pin jest `localeKeys` dentro i 476 verdi. (Il flag
   della memoria fee-surfaces resta aperto solo per la parte on-chain, §6.)
6. **Igiene repo**: main locale era 15 commit indietro → fast-forward a `0ad08e17`;
   **70 branch locali già merged cancellati** (`git branch -d`, solo safe delete,
   autorizzato dall'operatore; restano 21 branch non-merged).

## What remains

Ordine: prima ciò che blocca il mainnet. Etichette: **gate** · **owner** (code / operator /
third party) · **shape**. Vocabolario gate ESTESO rispetto al brief originale: oltre a
mainnet-blocking / post-launch / noise c'è **testnet-window accuracy** = vale ORA, mentre i
prospect (Manimama, Tulpar) vedono la demo e leggono il registry, ma si risolve da sé alla
cutover (il v2 è fee-less): non aspetta il go-live e non lo gate-a.

1. **RPagos internal audit** — mainnet-blocking · third party · finestra di audit su
   PR #73/`AUDIT_HANDOFF_ROUTERV2.md`; il repo è pronto, si aspetta il verdetto.
2. **MiCA written opinion** — mainnet-blocking · third party · parere scritto; nessun
   artefatto nel repo, stato non osservabile da qui.
3. **Deploy RSendsRouterV2 + cutover env** — mainnet-blocking · operator · deploy
   post-audit dello script esistente + settare `RSENDS_ROUTER_V2_ADDRESSES_JSON` senza
   toccare SetFeeConfig per le chain v2.
4. **Review di `DEPLOY_RUNBOOK.md` contro i requisiti reali della cutover** —
   mainnet-blocking · code (docs) · l'audit ha già evidenziato due lacune che il runbook
   non copre: il flip dei claim zero-fee condizionali (copy FAQ di PR #75, §6 — oggi non
   scritto da nessuna parte) e `RSENDS_ROUTER_V2_ADDRESSES_JSON` assente dal blueprint
   `render.yaml` (§5 — va settata a mano, il blueprint non la porterà mai). Due istanze
   dello stesso problema: la sequenza di go-live scritta non copre tutto ciò che la
   cutover richiede davvero — questa review è ciò che troverebbe le altre. Fattibile ORA,
   nella finestra dell'audit RPagos.
5. **`/app` env toggle** — mainnet-blocking · code · senza toggle test/live la UI su dati
   mainnet non esiste (gap accettato al ritiro del merchant dashboard); da costruire per
   operare il live.
6. **Terms §6, una frase** — testnet-window accuracy · operator (legal) · rivedere solo il
   claim "subscription-only": il contratto v1 (`RSendsRouter.sol:72-73`, §6) prova che
   nulla è dedotto dai settlement, ma una protocol fee payer-side esiste finché gira il
   v1; alla cutover il claim diventa vero da sé. Una frase, non il paragrafo.
7. **`/pay` fee disclosure** — testnet-window accuracy · operator poi code · il totale
   bundled senza riga fee (§6, `SummarySection` "No breakdown rows") tace una protocol fee
   che esiste solo finché gira il v1: alla cutover non c'è più nulla da nascondere. Se si
   vuole accuratezza già nella finestra demo: una riga di breakdown.
8. **CI advisory → gate: GitHub Pro ($4/mese)** — post-launch (ma decidere prima del
   mainnet) · operator · sblocca la branch protection sul repo privato (oggi impossibile:
   `gh api …/branches/main/protection` → 403 "Upgrade to GitHub Pro", §7) E porta i minuti
   Actions da 2.000 a 3.000/mese — indirizza sia il gate mancante sia l'esaurimento quota
   che ha aperto questo thread. **Il gate va sul merge, non sul deploy**: con i required
   checks su main niente atterra non verificato, main è verificato per costruzione, e
   l'auto-deploy Vercel/Render smette di essere un rischio senza riconfigurare nulla; il
   gating deploy-side comprerebbe la stessa protezione in un punto peggiore della pipeline.
9. **Copertura Redis-down/degraded** — post-launch · code · riscrivere i 4 test
   "pending rewrite" del circuit-breaker; il fail-closed è security-relevant e non testato.
10. **org_id re-key residuo** — post-launch · code · `payment_intents`/`merchant_webhooks`
    su org_id (22 call-site `resolve_owner_address` in 6 moduli), pass dedicato 3–5 giorni.
11. **Render MCP re-auth: query log 401 login + conflitto `INDEXER_USE_FINALIZED_TAG`** —
    post-launch · operator · lo stesso accesso mancante blocca due verifiche: il codice
    esatto del 401 di login prod (login-failure report) E quale valore di
    `INDEXER_USE_FINALIZED_TAG` sia attivo (blueprint dice `"true"`, il fix A/PR #44
    voleva `false` da dashboard; lag 0 non discrimina, §5). Un conflitto di config
    silenzioso sull'indexer resta zitto per mesi e poi si presenta come blocchi saltati:
    va nominato, non lasciato nella tabella env. Ri-autenticare via `/mcp` interattivo.
12. **Decisioni operatore pendenti invariate** — post-launch · operator · utenti pure-OAuth
    lockati (conteggio nel body di PR #25); fate delle chiavi `rsusr_`; Alembic drift→stamp
    su prod; cleanup env OAuth su Render/Vercel.
13. **Batch subtractive custodial + envelope errori + ritiro `/api/v1/keys/*` wallet-sig**
    — post-launch · code · invariati dal CLAUDE.md, non toccare drive-by.
14. **Annotazione `Event loop is closed` su job verde** — noise (ma da fare) · code ·
    silenziare il teardown perché le annotation error-level restino segnale.
15. **Residuo i18n EN + path venv stale negli skip** — noise · code · `twoPaths.developers.*`
    es/fr/de, `freeBadge` it/es; venv da ricreare per togliere il path `Desktop/…` dagli skip.

---
*Metodo: gh CLI (run/PR/API), suite locali complete incl. E2E Anvil (PG+Redis+anvil reali),
grep/lettura codice su main `0ad08e17`, probe HTTP read-only su prod (mai POST), Vercel MCP;
Render MCP unauthorized. Nessun file modificato oltre a questo report; nessun push; branch
cleanup locale autorizzato dall'operatore.*
