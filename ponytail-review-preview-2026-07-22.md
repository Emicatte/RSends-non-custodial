# Ponytail-review preview — RSends monorepo (2026-07-22)

**Preview only. Zero source changes made.** Findings use `<file>:L<line>: <tag> <what>. <replacement>. [~-N lines] [risk]` with tags `delete`/`stdlib`/`native`/`yagni`/`shrink` and risk tags:

- `[safe]` — no money-path/safety role; real cut candidate.
- `[verify]` — touches (or is named by) a safety invariant or closed finding; a **question**, not a cut. Each names what it serves and why it may still be excess.
- `[contract]` — Solidity; advisory only, routed to the RPagos audit.

`(untested — characterize before cut)` marks delete candidates with zero test coverage — per the guardrail these get a characterization test before any cut.

**Verification method:** every whole-module and high-value `delete` claim was independently re-verified by the coordinator with fresh greps across `app/`, `tests/`, `scripts/` (backend) and `app/ components/ hooks/ lib/ src/` excluding `_archive/` (web). Function-level claims carry the reviewing agent's grep evidence.

**Coverage:** all areas fully scanned, including a per-class/per-column audit of `services/backend/app/models` (no whole-module deletes there — every model module has importers; findings are class/column/validator-level, see the models subsection). ORM **column** cuts are migration-coupled: each needs an Alembic migration and is tagged `[verify]` regardless of deadness.

**Process note:** `~/.claude/skills/ponytail-review/` and `~/.claude/skills/ponytail/` exist but are **empty** (no SKILL.md, both created 2026-07-22 15:58 — broken install). This pass followed the format spec embedded in the operator prompt. Reinstall before the `/ponytail` cutting pass.

---

## Top section — confirmed dead / stub code (highest-value deletes)

These are zero-caller, verified-by-grep items. This closes the standing dead-code tripwire: the anticipated **legacy matcher subtree DOES still exist** (it lives inside `webhook_service.py`, not a separate module) and the **Alchemy webhook route was never implemented** (ghost references only).

### Backend — whole dead modules (all zero importers, coordinator-verified)

| Module | Lines | Risk | Note |
|---|---|---|---|
| `services/backend/app/errors.py` | ~105 | [safe] | `RSendError` + 23-code catalog, nothing imports it (incl. the pre-inventoried RULE_NOT_FOUND/RULE_PAUSED) |
| `services/backend/app/middleware/structured_logging.py` | ~111 | [safe] | duplicate JSON formatter **without secret redaction** — latent footgun if ever wired; real one is `logging_config.py` |
| `services/backend/app/security/input_validator.py` | ~262 | [verify] | CLAUDE.md's "Server-side validation always" invariant names this file as the canonical address-regex source; real validation lives in Pydantic schemas/services. Doc must move in the same pass that cuts it. (untested) |
| `services/backend/app/services/metrics.py` | ~107 | [safe] | Prometheus constants for deleted custodial modules; zero importers (untested) |
| `services/backend/app/services/rate_limiter.py` | ~170 | [verify] | zero importers; enforces nothing — and degrades **fail-open**, contradicting the fail-closed invariant. That posture is why it should go, but confirm nothing dynamic references it. (untested) |
| `services/backend/app/services/ws_ticket.py` | ~79 | [safe] | custodial sweep-feed WS tickets; surface gone (untested) |
| `services/backend/app/services/idempotency_service.py` | ~137 | [verify] | inbound-Alchemy-dedup era; own footer says idempotency moved to the `PaymentSettlement` UniqueConstraint. Live claims are in payment_indexer/webhook_service — named-invariant area, hence verify. Only its own test references it. |
| `services/backend/app/jobs/reconciliation_metrics.py` | ~33 | [safe] | never imported → collectors never registered; empties `app/jobs/` (untested) |
| `services/backend/app/api/ratelimit_routes.py` + `app/security/internal_auth.py` + EXEMPT_PATHS entry | ~119 (+138 test) | [safe] | sole caller was the Phase-A-deleted Next.js oracle; `internal/ratelimit` has 0 hits in apps/web |
| `services/backend/app/api/payment_ws.py` (+ wiring in `main.py:36,119,222,401`, dead call `webhook_tasks.py:130`) | ~265 | [safe] | zero frontend WebSocket usage (`/pay` polls REST); `notify_payment_completed` has zero callers, so even a WS client would only ever see `expired` |
| `services/backend/app/api/portfolio/[address]/portfolio-route.ts` | ~160 | [safe] | stray **Next.js TypeScript route inside the Python package** — unloadable by Python; hardcoded fake prices + sine-wave balance history |
| `services/backend/app/api/deps/user_api_key_auth.py` | ~60 | [safe] | pre-inventoried: `require_api_key_scope` wired to zero routes (`rsusr_` fate is a standing open decision) |

### Backend — the legacy matcher subtree (anticipated; found inside `webhook_service.py`)

- `services/backend/app/services/webhook_service.py:L406`: delete tier-1/tier-2 legacy matcher `match_and_complete_intent` + `_complete_intent` (L567) + `_handle_late_payment` (L338) + `try_extract_reference_id`/`_REF_ID_PATTERN` (L314) + scoring constants (L194–205). Zero callers (coordinator-verified); `app/api/routes.py:153-155` states matching moved to the indexer. [~-320 lines] [verify — pre-indexer matching path, money-path-shaped: remove as a deliberate pass with characterization, not a drive-by] (untested — characterize before cut)
- `services/backend/app/services/webhook_service.py:L610`: delete v2 matcher `match_transaction_to_intent` + `V2_SCORE_*` (L207–219) + `CHAIN_NETWORK_MAP` (L222 + inline dup L515–518). Zero callers; its documented consumer `finalize_match` (L878) is itself dead (only other mention: its docstring at L639). After both go, `_finalize_event_type` (L1109) has zero production callers (pinned only by `test_webhook_contract.py`). [~-280 lines] [verify — same matching-scope caveat] (untested — characterize before cut)

### Ghost references / stubs

- `services/backend/app/middleware/idempotency.py:L49`: delete `if "alchemy" in request.url.path` — the Alchemy webhook route was **never implemented**; branch can never match. [~-3 lines] [safe]
- `services/backend/app/security/api_keys.py:~L31-58`: delete dead `EXEMPT_PATHS` entries `/api/internal/signing`, `/api/internal/oracle`, `/api/v1/forwarding`, `/api/v1/distributions` — no such routes exist. [~-4 lines] [verify — auth-perimeter list; removal is strictly tightening]
- Custodial-path residue riding along: `app/middleware/db_backpressure.py:L27`, `app/middleware/idempotency.py:L14`, `app/middleware/request_timeout.py:L21` (SWEEP_PATH_MARKERS), `app/tasks/notification_tasks.py:L80` (self-documented: batches "which no longer exist"). [~-15 lines] [safe]
- `apps/web/lib/useSweepWebSocket.ts` + `lib/useSweepStats.ts`: self-labeled **INERT stubs** with `TODO(cleanup)`; `useSweepWebSocket` is still wired into `app/[locale]/page.tsx:17,:746` (delete-with-edit), `useSweepStats` has zero importers. [~-60 lines] [safe]
- `apps/web/app/[locale]/page.tsx:L850`: `AntiPhishingSetup` modal is **unopenable** (`showAntiPhishing` never set true) → `app/AntiPhishingSetup.tsx` (202 lines) is effectively dead and is the only writer of `rsend_antiphishing_code`. [~-210 lines] [verify — silently-broken feature, product decision: resurrect or retire; keep the logout key-clear until the key can't exist in the wild]

### apps/web — dead custodial/multi-chain clusters (zero importers outside each cluster, coordinator-verified)

- 16 dead hooks (pre-inventoried): `hooks/useUserRoutes`, `hooks/useTabTransition`, `lib/{useClipboardDetection, useDistributionList, useForwardingRules, useGaslessPaymaster, useGuardedAction, useIdempotencyKey, useKeyboardShortcuts, usePermit2, usePermit2Flow (392L, targets `transferWithPermit2` — an ABI that exists only on archived FeeRouterV3/V4), usePortfolioData, useSplitContracts (364L), useTabLock, useSweepStats, useBackendCallback}` [~-1,800 lines] [safe]
- Their support layer: `lib/walletAuth.ts` (201L — wallet-sig header builder for the frozen backend routes; [verify] only because it maps to the documented post-Manimama retirement), `lib/rsendFetch.ts` (44L) [safe]
- Transitively dead API routes: `app/api/paymaster/[network]/route.ts`, `app/api/portfolio/[address]/route.ts`, `app/api/tx/callback/route.ts` [~-150 lines] [safe]
- Dead standalone components: `components/FeatureDisabled.tsx`, `components/auth/AuthButtons.tsx` (orphan; live variant is `LandingAuthButtons`), `components/motion/MagneticButton.tsx`, `components/motion/Stagger.tsx`, `components/shared/ErrorBoundary.tsx` [~-400 lines] [safe]
- Root-app custodial console leftovers, all zero importers: `app/StatusCards.tsx` (100L), `app/NetworkSelector.tsx` (359L), `app/EmergencyStop.tsx` (123L), `app/AccountHeader.tsx` (370L — imported by the landing page but never rendered), `app/TokenSelector.tsx` (285L), `app/ExploreTokens.tsx` (151L) + `components/mockups/{DesktopMockup,IPhoneMockup}.tsx` (549L) + `hooks/useMarketDataLive.ts` (67L) + `app/api/tokens-market/route.ts` (84L — a live unauthenticated CoinGecko proxy serving nobody, [verify] confirm no external caller in prod logs), `app/overlays/ApiDocsOverlay.tsx` (482L) [~-2,570 lines] [safe unless noted] (all untested — characterize before cut)
- CCIP residue: `lib/ccipRegistry.ts` (103L), `lib/ccipMonitor.ts` (45L) — zero importers [safe]

### Backend repo clutter (not code — one `rm` pass)

`services/backend/`: `dev.db.broken-*`, `qa_test.db`, `stress_s4.db`, `stress_s6.db`, `test.db`, `rpagos.db.backup-*`, `dump.rdb`, `Dockerfile 2`, `.dockerignore 2`, `_archive/` scripts. Repo root: prod dumps (`*.dump` now gitignored per 7e43911e — verify none remain tracked).

---

## Area 1 — services/backend

### app/services (beyond the top-section modules)

- `app/services/payment_indexer.py:L145`: shrink two near-identical topic helpers (`_payment_made_topic`, `_split_payment_made_topic` L176) each wrap keccak in try/except with a `"0xUNRESOLVED_RECOMPUTE_TOPIC"` sentinel for "minimal envs", but eth-utils is a pinned hard dep (requirements.txt:31). One `_topic(sig)` helper, direct import. [~-20 lines] [verify — these constants ARE the getLogs matching filter; the fallback is inert flexibility whose sentinel would silently match zero events (see out-of-scope note 1)]
- `app/services/payment_indexer.py:L748`: yagni `_finalize_settlement` never uses its `chain_id` param (single call site L1100). Drop it. [~-1 line] [safe]
- `app/services/payment_indexer.py`: **no other findings** — the finality/depth-mode, reorg reconciler, ratchet pins, chunking/clamp, claim rows are all earned (F-1/F-10, B-1/B-2, PR #52/#58, tip-race clamp). 1,599 lines, almost entirely load-bearing.
- `app/services/webhook_service.py:L962`: shrink `expire_stale_intents` has zero app callers; `app/tasks/webhook_tasks._expire_pending_intents_async` reimplements the identical sweep inline (both apply `settlement_hold_exists`). Make the task call the tested service function. [~-25 lines] [verify — the B-1 settlement-hold guard currently exists in TWO copies; merging removes divergence risk, but both are load-bearing until merged]
- `app/services/webhook_service.py:L1003`: shrink `_dispatch_event` and `send_webhook` (L1388) are near-duplicate dispatchers (same webhook query, env filter, idem-key format, delivery insert; differ only in Redis dedup + immediate attempt). Fold into one with `immediate: bool`. [~-45 lines] [verify — webhook dispatch idempotency; the duplication already lets the two surfaces diverge on Redis dedup (see out-of-scope note 4)]
- `app/services/webhook_service.py:L1165`: shrink `_attempt_delivery` and `send_test_event` (L1296) duplicate egress re-check + timestamp + HMAC + headers + POST. Extract one signed-POST helper. [~-30 lines] [verify — SSRF egress guard + HMAC path; refactor must keep the pre-POST re-check and signed bytes byte-identical]
- `app/services/circuit_breaker.py:L807`: delete `DependencyGuard` + singleton (L894) + `SweepBlockedError` (L96) — custodial sweep pre-flight, zero callers. [~-115 lines] [safe] (untested — characterize before cut)
- `app/services/circuit_breaker.py:L392`: delete `force_open`/`force_close` + `_LUA_FORCE_STATE` (L224-248) — zero callers; the only test hit is a test *name* asserting the health loop does NOT force-open. [~-90 lines] [safe] (untested)
- `app/services/circuit_breaker.py:L455`: delete `get_state()` — zero callers. [~-8 lines] [safe] (untested)
- `app/services/circuit_breaker.py:L739`: delete `circuit_breaker()` decorator + fallback machinery — zero app callers; exercised only by `test_circuit_breaker.py` (remove that test class in the same PR). [~-53 lines] [safe]
- `app/services/circuit_breaker.py:L118`: yagni Redis-backed Lua state layer (`_LUA_CHECK_ALLOWED`/`_LUA_RECORD_RESULT` L118-221, `_check_redis`/`_record_redis` L466-529) provides cross-process breaker sharing; the in-memory path implements the same machine and every consumer lives in one process. [~-150 lines] [verify — RPC failover/health (PR #50) rides these breakers; confirm Render worker count is truly 1 process before cutting shared state]
- `app/services/aml_service.py:L549`: delete `screen_transaction` back-compat API — docstring names `sweep_service.py`, which no longer exists; zero callers. [~-36 lines] [safe] (untested)
- `app/services/aml_service.py:L671`: delete `check_split_plan` (custodial split-plan structuring detection) — zero callers; the non-custodial split path never invokes it. [~-77 lines] [verify — AML named-invariant area, but it currently protects nothing: no split path calls it] (untested)
- `app/services/aml_service.py:L640`: delete `add_to_blacklist` + `remove_from_blacklist` (L750) — zero callers (aml_routes uses only `full_aml_check` + `load_sanctions_from_json`). [~-45 lines] [verify — sanctions tooling; confirm no operator runbook shells into these] (untested)
- `app/services/aml_service.py:L176`: pre-inventoried — legacy `blacklisted_wallets` lookup still queried alongside `sanctions_list`. [verify — AML surface; superseded table, but the check is live]
- `app/services/rpc_manager.py:L486`: delete `consensus_call` (majority-read across 3 providers for "balance, nonce" — custodial-era). Zero callers. [~-86 lines] [safe] (untested)
- `app/services/rpc_manager.py:L575`: delete `send_raw_transaction` — zero callers; `tests/test_no_custodial_surface.py:12` pins it as "a dormant zero-caller helper" via allowlist. Deleting **strengthens** the no-custodial pin; move the allowlist entries (L42, L66) in the same change. External grep hits are web3's own `w3.eth.send_raw_transaction` in payer-side test/scripts, not this helper. [~-28 lines] [verify — the pin test deliberately documents this symbol; test moves with the delete]
- `app/services/rpc_manager.py:L636`: shrink `start_all_managers` has one caller; inline. [~-5 lines] [safe]
- `app/services/router_registry.py:L560`: delete `TokenMetadataMismatch` — defined, never raised (guard raises `SystemExit`). [~-3 lines] [safe]
- `app/services/cache_service.py:L300`: delete Alchemy/portfolio cache accessors (`get_token_metadata`/`set_token_metadata`/`get_portfolio`/`set_portfolio`/`get_prices`/`set_prices`) — zero callers. [~-36 lines] [safe] (untested)
- `app/services/cache_service.py:L342`: delete `check_rate_limit` twin sliding-window — zero callers; **fail-open** ("Se Redis è down, permetti"), the opposite of the enforced posture. [~-35 lines] [verify — rate-limit named area; the fail-open posture is exactly why it should go, confirm nothing dynamic references it]
- `app/services/cache_service.py:L241`: delete generic cache layer (`cache_get`/`cache_set`/`cache_delete`, `InMemoryCache`/`_memory_cache` L121-158, `_redis_cb` L36-41) — after the accessor cut, only `test_circuit_breaker.py` uses it. Also resolves the module running TWO Redis breakers at once. [~-100 lines] [verify — CLAUDE.md's Redis-DOWN follow-up notes the in-memory-fallback test is "skipped pending rewrite"; the cut moots that follow-up and should be recorded as such, not done silently]
- `app/services/cache_service.py:L232`: delete `_redis_ping` — zero callers. [~-4 lines] [safe]
- `app/services/alert_service.py:L53`: delete 12 producer-less `AlertType` members + SEVERITY_MAP rows (`SIGNING_SPIKE`, `AML_BLOCK`, `SWEEP_FAILED`, `BALANCE_LOW`, `SYSTEM_IMBALANCE`, `LEDGER_DISCREPANCY[_CRITICAL]`, `ONCHAIN_DISCREPANCY[_CRITICAL]`, `STALE_TRANSACTIONS`, `TREASURY_MISMATCH[_CRITICAL]`) — the named producer `reconciliation_job.py` doesn't exist. [~-24 lines] [safe]
- `app/services/alert_service.py:L320`: delete `critical_alert` + `_send_legacy_webhook` — only caller is dead `circuit_breaker.force_open`. [~-54 lines] [safe] (untested)
- `app/services/notification_service.py:L95`: delete typed-notification layer (`format_*`/`_FORMATTERS` L95-161, `send_notification` L224, `enqueue_notification` L256) — sole consumer is Celery `send_notification_task`, which nothing ever enqueues. Keep `send_telegram_alert` + `_check_rate_limit` (live via approval_notify + alert_service). Cascades into `app/tasks/notification_tasks.py`. [~-120 lines] [safe] (untested)
- `app/services/signing_rate_limit.py:L43`: delete `check_signing_rate_limit` — zero callers; guards a signing endpoint that no longer exists. Keep `check_nonce_uniqueness` (live). [~-70 lines] [verify — fail-closed limiter by design; fold into the documented wallet-sig retirement pass]
- `app/services/wallet_session.py:L68`: delete `revoke_wallet_session` — zero callers. [~-11 lines] [safe] (untested)
- `app/services/user_api_key_service.py:L41`: delete `MAX_KEYS_PER_USER` alias + `count_active_keys` per-user back-compat (L98-111) — zero callers. [~-16 lines] [safe] (untested)
- `app/services/siwe_service.py:L62`: delete `MAX_WALLETS_PER_USER` alias — zero callers. [~-2 lines] [safe]
- `app/services/price_service.py:L120`: delete `get_eur_value`/`get_usd_value` — zero callers (stats uses `get_price`). [~-14 lines] [safe] (untested)
- `app/services/key_usage_service.py:L20`: delete `add_volume` — zero callers. [~-8 lines] [safe] (untested)
- `app/services/aml_exceptions.py:L9`: delete `AMLReviewRequired` — zero references. [~-5 lines] [safe]

Lean, no findings: `intent_service.py`, `email_auth_service.py`, `org_service.py`, `org_invite_service.py`, `owner_identity.py`, `audit_service.py`, `auth_service.py`, `account_deletion_service.py`, `onboarding_service.py`, `invoice_service.py`, `account_linking_service.py`, `approval_notify.py`, `auth_audit.py`, `chain_access.py`, `split_math.py`, `password_service.py`, `email_service.py`, `device_fingerprint.py`, `hmac_service.py`, `external_health.py`, `anomaly_service.py`.

### app/api routes

- `api/aml_routes.py:L74`: delete `POST /api/v1/aml/check` — its caller (Next.js oracle) was deleted in Phase A; the web proxy **denylists** the path (`apps/web/app/api/backend/[...path]/route.ts:61`). Remove route + `AMLCheckRequest/Response` schemas. [~-57 lines] [safe] (untested)
- `api/aml_routes.py:L106,170,205,238`: delete the 4 `admin/aml/*` routes — zero frontend callers (proxy denylist only), zero route tests; they read/mutate `AMLAlert` rows whose ONLY writer is the dead `/aml/check` above. Cascade: `aml_service.py` (766L) and `aml_models.py` (169L) become fully caller-less. [~-254 lines, ~-1,189 with cascade] [verify — documented X-Admin-Token surface in CLAUDE.md's admin table; doc moves in the same pass; `data/sanctions/ofac_sdn.json` disposition is an operator decision]
- `api/audit_routes.py:L70`: delete-candidate `GET /api/v1/audit/log` — zero frontend callers (proxy denylists `api/v1/audit`), zero route tests. `require_admin` itself is imported by 3 other modules and **stays**. [~-62 lines] [verify — documented admin surface; operator curl access may be intentional] (untested)
- `api/price_routes.py:L24`: delete `GET /api/v1/prices/{coingecko_id}` — zero callers (frontend hits only the list endpoint, which is live — keep it). [~-9 lines] [safe]
- `api/api_key_routes.py:L175,237`: delete `GET /{key_id}/usage` + `DELETE /{key_id}` (permanent hard-delete) — dead beyond the documented retirement scope: zero hits incl. the archived merchant dashboard; proxy denylists `api/v1/keys`. Hard-delete also erases the org-keyed audit row 0014 made load-bearing. [~-57 lines] [verify — file is the documented wallet-sig retirement follow-up; this shrinks the frozen surface without touching generate/list/revoke]
- `api/auth_routes.py:L58-76`: delete `_set_auth_cookies` — never called (refresh sets its cookie inline; login lives in auth_email_routes with its own copy). [~-19 lines] [safe]
- `api/organizations_routes.py:L62` (+4 copies): shrink 5 byte-identical `require_user_id` copies across route files (8 total incl. scheduled-removal files); `user_onboarding_routes.py:28` even imports it from a sibling route module. One copy in `app/api/deps/`. [~-44 lines] [safe]
- `api/user_account_routes.py:L69-92`: shrink `require_user_id` is a strict subset of `require_user_and_sid`; folds into the dedup above. [~-11 lines] [safe]
- `api/user_api_keys_routes.py:L57`: yagni `GET /available-scopes` returns a constant behind a full org-role DB round-trip; sole caller (`hooks/useUserApiKeys.ts:119`) could ship the constant in the bundle. Live caller → coordinated change. [~-11 lines] [safe]
- `api/health_routes.py:L120-122`: delete `_check_kms` stub — hardcoded `"skipped"` forever; remove check + wiring (L137,139). `/health/deep` itself is operationally live — keep. [~-12 lines] [safe]
- `api/organizations_routes.py:L108-120,139-150,208-217`: shrink `OrganizationResponse` built field-by-field 3×; one `_org_response()` helper. [~-20 lines] [safe]
- `api/merchant_routes.py:L15,113-115`: delete `_generate_intent_id` + `secrets` import — construction moved to `intent_service.create_intent` (Phase D). [~-4 lines] [safe]
- `api/merchant_routes.py:L20,45-58,60`: delete 9 unused imports left by the Phase D refactor (`func`, `generate_reference_id`, `resolve_recipient`, `derive_invoice_id`, `chain_is_supported`, `token_is_enabled`, `check_monthly_limits`, `increment_intent_count`, `timedelta`). [~-9 lines] [safe]
- `api/merchant_profile_routes.py` + `merchant_invoice_routes.py`: yagni — JWT-authed but NOT in `EXEMPT_PATHS`, so prod 401s them before their own auth (CLAUDE.md plan anchor 10). Frontend hooks exist but cannot work in prod: 363 lines serving nothing in production. Decision needed (add exempt entry or archive), not a cut. [0 lines counted] [verify — documented Phase-C deferral; EXEMPT_PATHS is an auth-perimeter change]

No findings (verified live, no accidental layers): `auth_email_routes.py`, `user_wallets_routes.py`, `user_account_routes.py` routes, `account_settings_routes.py`, `notification_routes.py`, `org_invites_public_routes.py`, `user_onboarding_routes.py`, `deps/require_org_role.py` (approval gate is security-earned), `wallet_session_routes.py` (inside documented retirement scope).

### app/models (per-class/per-column audit; column cuts are migration-coupled)

- `models/api_key_models.py:L9,15`: delete `KeyScope` + `KeyEnvironment` enums — zero refs outside the module; `ApiKey.scope`/`.environment` are plain String columns, not these enums. [~-11 lines] [safe] (untested)
- `models/notification_schemas.py:L27`: delete `KnownDeviceResponse` — zero importers; `user_account_schemas.py:L33` holds a near-identical live copy (only diff `str` vs `UUID` id). Duplicate + dead. [~-9 lines] [safe] (untested)
- `models/auth_models.py:L212`: shrink `AuthAuditLog.google_sub` column + the dead kwarg in `auth_audit.record_auth_event` — zero callers pass it; always NULL (users-table OAuth columns dropped in 0010, this one survived). Kwarg cut free; column cut needs migration. [~-3 lines] [verify — migration-coupled; social-login-removal residue] (untested)
- `models/auth_models.py:L189,140,98`: shrink dead columns `UserSession.device_fingerprint` (never written), `User.metadata_json` (never read/written), `User.avatar_url` (one read in `/me`, ZERO writers since social-login removal → permanently NULL). Each needs a migration. [~-4 lines + schema fields] [verify — migration-coupled]
- `models/auth_models.py:L29-71` + `models/db_types.py:L18,29`: shrink two parallel hand-rolled cross-dialect TypeDecorator sets in the same package (`_JSONB` ≡ `JSONBType`, `_INET` ≡ `InetType`), used by disjoint model files. Consolidate into one module. [~-25 lines] [safe]
- `models/db_models.py:L38`: yagni `AnomalyType.unusual_network` — never emitted (`anomaly_service` emits 3 other types only). [~-1 line] [safe] (untested)
- `models/db_models.py:L137`: shrink `AnomalyAlert.resolved` — never read or written. Migration-coupled. [~-1 line] [verify] (untested)
- `models/schemas.py:L130`: shrink `CallbackResponse.matched_intent_id`/`.webhook_triggered`/`.matching` — permanently-default fields; the sole constructor (`routes.py:159`) never passes them (deposit-address matching removed). [~-3 lines] [safe]
- `models/schemas.py:L101-123`: native three hand-rolled allowlist validators on `TransactionCallbackPayload` → `Literal[...]` types. Legacy callback surface, low priority. [~-24 lines] [safe]
- `models/email_auth_schemas.py:L85,98,107` + `org_schemas.py:L25`: shrink three byte-identical `_normalize_email` validators + `EMAIL_RE` duplicated verbatim as `_EMAIL_RE` — one shared `Annotated[str, ...]` type covers all four classes. (`EmailStr` deliberately avoided — `email-validator` not in requirements — hence shrink, not native.) [~-20 lines] [verify — email normalization backs the one-account-per-email invariant (uq_users_email_lower); consolidation must keep `lower().strip()` semantics identical]
- `models/email_auth_schemas.py:L73` + `models/onboarding_schemas.py:L131,138`: native must-be-true validators → `Literal[True]` fields (`terms_accepted`, `accept_documents`, `age_attested`). [~-18 lines] [safe]
- `models/merchant_models.py:L294,376,386`: native/shrink three hand-rolled EVM-address validators, each with inline `import re` and its own copy of `^0x[a-fA-F0-9]{40}$` (also duplicated in `org_schemas._EVM_ADDR_RE` and `schemas.py:97`) — the codebase already uses `Field(pattern=...)` natively (`user_wallets_schemas.py:21`). One shared lowercasing Annotated type. [~-24 lines] [verify — recipient-gate input validation (Phase B); consolidation must keep reject-not-coerce + lowercase behavior identical]
- `models/merchant_models.py:L360,368,578`: native `validate_late_payment_policy`/`validate_currency`/`validate_action` allowlists → `Literal[...]`. [~-21 lines] [safe]
- `models/merchant_models.py:L588`: shrink `MerchantTransactionItem` is a 19-field subset of `PaymentIntentResponse` — two parallel serializers over the same ORM row. Consolidation candidate, both live. [~-27 lines] [verify — API response contracts for merchant GET/list; field set changes are a docs/data-contract change]
- `models/notification_models.py:L41-44`: yagni `telegram_chat_id` (provably unwritable — PATCH schema omits it, sender uses global settings) + `telegram_tx_confirmed`/`_failed`/`_price_alerts` (writable, consumed by nothing — docstring: "reserved for future wiring"). [~-8 lines + migration] [verify — product decision + migration-coupled] (untested)
- `models/invoice_models.py:L61,64`: yagni `Invoice.tax_regime`/`tax_note` — only writes are literal `None`; "riempito dal commercialista" placeholder with no UI/route to fill it. Documented-intentional → flag-only. [0 lines, decision item] [verify]
- `models/aml_models.py:L56`: delete-scheduled `BlacklistedWallet` — CLAUDE.md already batches it ("dead, superseded by sanctions_list") but `aml_service` still queries it; zero test refs to ANY aml_models class. Needs migration. [~-11 lines + service paths] [verify — AML surface + migration]
- `models/aml_models.py:L132`: shrink `AMLAlert.sar_filed` — read-only serialized, no writer → always False. Migration-coupled. [~-1 line] [verify] (untested)
- Custodial-residue models riding the scheduled router removal (~340 lines, zero test refs, each table cut needs a migration): `user_routes_models/schemas` (~-72), `user_tx_models/schemas` (~-159), `user_contacts_models/schemas` (~-109) — sole referencers are the three routers CLAUDE.md batches for removal; `merchant_profile_models/schemas` stays flag-only (19 live refs via owner_identity/invoices; "migrate billing fields first"). [verify — belongs to the documented batch pass, not a drive-by]

Not flagged (verified alive/deliberate): `dashboard_schemas.DashboardStats` (pinned base of `OrgDashboardStats`, CLAUDE.md keeps it untouched), `VALID_EVENTS`, `IntentStatus` (legacy alias documented), all settlement/indexer/org/wallet/api-key/consent models, `audit_models.LedgerAuditLog.hmac_signature` (written at `audit_service.py:197`).

### middleware / security / top-level / tasks / db / tokens

- `security/api_keys.py:L14,19,22`: delete unused imports `hmac`, `functools.wraps`, `HTTPException`. [~-3 lines] [safe]
- `security/api_keys.py:L78-84`: delete `GET_PUBLIC_PREFIXES` entries `/api/v1/ledger`, `/api/v1/splits`, `/api/v1/health/sweep` — no such routes exist. [~-3 lines] [verify — GET deny-by-default allowlist; removal strictly tightens]
- `security/api_keys.py:L140,183-215`: yagni v1 SHA-256 legacy lookup + auto-upgrade dual path in `verify_api_key` + v1 `key_hash` stamping. [~-35 lines] [verify — API-key auth path; needs prod `SELECT count(*) FROM api_keys WHERE hash_version=1` = 0 before cut]
- `middleware/rate_limit.py:L114,370-371`: yagni `RATE_LIMIT_EXEMPTIONS` empty-set check on every request since inception. [~-5 lines] [verify — fail-closed surface; no-op today, removal behavior-identical]
- `middleware/rate_limit.py:L12-19`: shrink stale docstring limit table (drifted from `ENDPOINT_LIMITS`). Replace with a pointer. [~-8 lines] [safe]
- `config.py:L239`: delete `_HEX_KEY_RE` — sweep-key-era, zero references. [~-1 line] [safe]
- `config.py:L100-103`: yagni `indexer_reorg_safety_depth` self-documents as INERT ("env compatibility only"); only ref is a no-op monkeypatch in one e2e test. [~-4 lines] [verify — F-1 superseded it deliberately; confirm the Render env var is unset first]
- `config.py:L8`: delete unused `import sys`. [~-1 line] [safe]
- `config.py:L291-300`: shrink `validate_settings` docstring still documents SWEEP_PRIVATE_KEY/SIGNER_MODE rules it no longer implements. [~-5 lines] [safe]
- `main.py:L451-459`: yagni `/health/rpc` hardcodes 4 chains incl. ethereum/arbitrum with nothing configured; derive from configured indexer chains. [~-3 lines] [verify — PR #50 observability; confirm ops doesn't rely on fixed labels]
- `main.py:L92`: shrink `is_redis_healthy` imported in lifespan but unused there. [~-1 line] [safe]
- `db/session.py:L77-96`: delete `db_write_lock`/`_sqlite_write_lock` — zero callers; WAL/busy_timeout pragmas already handle it. [~-20 lines] [safe] (untested)
- `celery_app.py:L38-55`: yagni `confirm`/`analytics`/`dlq` queues + `_dlq_exchange` — no task routes to any; nothing ever publishes to the DLQ. Keep `notify` + default. [~-10 lines] [safe]
- `celery_app.py:L31-34,104-106`: shrink decorative section headers + stale worker-count docstring. [~-6 lines] [safe]
- `app/tasks/{webhook,notification,email,deletion}_tasks.py`: stdlib/shrink `_run_async` 12-line event-loop dance copy-pasted 4×. One shared helper. [~-33 lines] [safe]
- `tokens/registry.py:L72-84`: delete `get_native`/`get_tokens_for_chain`/`get_decimals` — zero callers (live consumers use `get_token` + `get_all_coingecko_ids`). [~-14 lines] [safe] (untested)
- `tokens/registry.py:L27`: yagni `TokenInfo.min_amount` — set on all 15 entries, read nowhere. [~-2 lines net] [safe]
- `tokens/registry.py:L47-63`: yagni Ethereum-mainnet + Arbitrum token entries — no router/indexer/intent path can settle there today (active-chain SSOT = router_registry, Base only). [~-10 lines] [verify — forward config for mainnet expansion; harmless but speculative]
- `observability.py:L1-72` (+ `main.py:L67-71`, requirements.txt:L49-54): yagni full OTel setup gated on `OTEL_ENDPOINT`, set in no environment; 5 pinned deps ride along. [~-80 lines + 5 deps] [verify — pure observability; confirm no Render env sets OTEL_ENDPOINT]

**net (services/backend): ~-5,800 lines possible** (services ~-2,400 of which ~-880 [safe]; routes ~-2,300 of which ~-460 [safe] zero-caller zero-test; models ~-520 of which ~-150 [safe] code-only; middleware/top-level ~-620) — plus ~-420 lines of tests for deleted surfaces. The [verify]-tagged majority needs the named confirmations (prod hash_version query, admin-surface intent, single-process deployment, Alembic migrations for column cuts, doc moves) before the `/ponytail` pass.

---

## Area 2 — apps/web

### Structure / duplication

- `src/config/chains.ts:L11`: yagni fourth parallel EVM chain registry (10 chains) duplicating `lib/contractRegistry.ts` REGISTRY, the dead `CHAINS` array in the landing page, and `providers.tsx` EVM_CHAIN_IDS. Sole importer: `lib/chain-adapters/evm-adapter.ts` (itself only reachable from the dead landing widget). [~-223 lines] [safe]
- `src/constants/addresses.ts:L17`: yagni Uniswap V3 router/quoter/factory/multicall for 10 chains — the app never swaps; no live path uses any entry. [~-124 lines] [safe]
- `src/constants/abis/uniswapV3Router.ts:L1`: delete — zero importers. [~-97 lines] [safe] (untested)
- `src/types/chain.ts:L1`: delete — falls with the two above. [~-57 lines] [safe]
- `src/components/ChainLogo.tsx:L1`: delete — sole importer is the never-rendered landing widget. [~-191 lines] [safe] (untested)
- `lib/chain-adapters/` (6 files): yagni universal EVM/Solana/Tron adapter abstraction — `registry.getAdapter` has zero consumers outside the folder; external importers are `providers.tsx` (registers 13 adapters at module load, result never queried) + the dead cluster. [~-852 lines] [verify — providers.tsx runs on every page; removal touches the global provider tree — verify /pay and wallet-connect still mount]
- `hooks/` vs `lib/use*.ts`: no live overlap — the split is temporal (session-era vs custodial-era), not functional. No finding beyond the dead-hook inventory.

### Oversized files (dead weight inside living files)

- `app/[locale]/page.tsx:L64`: delete `ParticleIntro` — defined, never rendered (`showIntro` init false, never set true). [~-79 lines] [safe]
- `app/[locale]/page.tsx:L144`: delete `NetworkTokenWidget` + `CHAINS` + `_alch`/`_inf` env helpers (L144-512) — never rendered; the ONLY consumer of `ChainLogo`, `ChainFamilySwitch`, `TokenRow`, `useTron`, solana wallet hooks on the landing. [~-370 lines] [safe]
- `app/[locale]/page.tsx:L517`: delete `EngineStatus` — never rendered. [~-22 lines] [safe]
- `app/[locale]/page.tsx:L689-757`: delete dead state/derivations in `Home` (`useUniversalWallet` for an `AccountHeader` imported-never-rendered; `selectedChainId`/`selectedToken`/`useTokenBalance`/`useTokenPrices`; `unseenCount` never read). Page shrinks 866 → ~350 lines of real marketing hero. [~-60 lines + imports] [safe]
- `components/FooterGlobe.tsx:L262`: delete `GlobeCanvas` + supporting data/math (CITIES/ARCS/TOKENS/500-point LAND table/3D math, L16-256) — `<GlobeCanvas` never rendered in the JSX; footer renders only the links bar. Keep `COLUMNS` (asserted by `footerLinks.test.ts`) + social icons. 679 → ~160 lines. [~-520 lines] [safe]
- `lib/contractRegistry.ts:L208`: shrink REGISTRY to the two payable chains (Base 8453, Base Sepolia 84532) — live consumers use only `getRegistry(chainId).blockExplorer/…` (`lib/web3/explorer.ts:7`, `app/pay/_components/payUi.tsx:11`); all other importers are dead-cluster. [~-300 lines] [verify — explorer.ts serves live /pay receipt links; keep the two kept entries byte-identical]
- `lib/contractRegistry.ts:L163-205`: yagni legacy `NEXT_PUBLIC_FEE_ROUTER_V4/_V3/_ADDRESS` env fallbacks + 5 per-chain V4 getters no deployment sets — every non-Base entry resolves to the zero address; `getFeeRouterAddress`'s only caller is dead `evm-adapter.ts`. [~-45 lines] [safe]
- `lib/contractRegistry.ts:L522-556`: delete `TRON_REGISTRY`/`getTronRegistry`/`isTronFeeRouterAvailable` — zero importers; contains placeholder `'T_INDIRIZZO_DAL_DEPLOY'`. [~-35 lines] [safe]
- `lib/contractRegistry.ts:L609`: delete `EUR_RATES` hardcoded mock — zero importers. [~-20 lines] [safe]
- `lib/contractRegistry.ts:L21,602`: delete `POOL_FEE` + `findChainForToken` — zero external importers. [~-15 lines] [safe]
- `components/settings/OrganizationSettings.tsx:L675,867` + `WalletsSettings.tsx:L359`: shrink `MemberRow`/`InviteRow`/`WalletRow` triplicate the same 5s confirm-timeout effect + confirm/cancel button pair + badge styles. Extract one `ConfirmDangerButton` + shared styles. [~-150 lines] [safe]
- `components/app/CreatePaymentModal.tsx`: no finding — dense but every branch live (PR #60), test-covered.
- `lib/web3/useHostedCheckout.ts`: no finding — money-path, all branches reachable, test-covered.

### Multi-chain yagni (Solana/Tron/universal-wallet cluster)

- `app/providers.tsx:L12-29`: yagni registers 11 EVM + Solana + Tron adapters at module load and mounts `SolanaProviders`/`TronProvider` on every non-admin/non-pay page — only UI consumer is the unrendered widget. Drop adapter registration + both mounts after the page.tsx cut. [~-30 lines here, unlocks cluster] [verify — providers.tsx also hosts the wagmi safeConfig/WalletStackFull gate used by live auth+checkout; touch only the solana/tron/adapter lines]
- `hooks/useUniversalWallet.ts:L1`: delete — sole importer is the dead widget. [~-92 lines] [safe]
- `hooks/useTronWallet.ts:L1`: delete — sole importer `app/providers-tron.tsx`. [~-236 lines] [safe]
- `app/providers-tron.tsx:L1` + `app/providers-solana.tsx:L1`: delete — consumers are the providers.tsx mount + dead cluster. [~-70 lines] [verify — same providers.tsx caveat]
- `components/shared/ChainFamilySwitch.tsx:L1`: delete — sole importer is the dead widget. [~-70 lines] [safe]
- `app/hooks/useNonEvmPortfolio.ts:L1`: delete — zero importers. [~-78 lines] [safe] (untested)
- `app/hooks/useMultiTokenBalances.ts:L1`: delete — zero importers. [~-111 lines] [safe] (untested)
- `app/hooks/useTokenBalance.ts` + `useTokenPrices.ts`: delete after page cut — remaining importers are dead-cluster. [~-153 lines] [safe]
- `app/tokens/tokenRegistry.ts`: delete after cluster cut — importers reduce to dead files + dead tokens-market route. [~-357 lines] [safe]
- `lib/types/tokenMarket.ts`: delete after the tokens-market/mockups cluster. [~-30 lines] [safe]
- Bundle bonus: cluster removal drops 7 heavy client deps (`@solana/*` ×6, `tronweb`).

### Orphan marketing pages (product decision, not a bare cut)

- `app/[locale]/markets/` + `app/[locale]/token/[id]/` + `hooks/useCoinGecko.ts` + `lib/coingeckoCache.ts` + `app/api/market/[...path]/route.ts`: yagni — zero inbound links from MarketingNav or the footer COLUMNS; reachable by URL only, cross-link only each other. [~-982 lines] [verify — cannot tell if intentionally unlisted (SEO/soft-launch); operator decides. `lib/coingeckoUpstream.ts` stays if /api/market stays]

**net (apps/web): ~-6,900 lines possible** (~-5,800 of it [safe]), rising to **~-7,900** if the orphan markets cluster is confirmed cut — plus the `@solana/*`/`tronweb` bundle drop.

---

## Area 3 — packages/contracts (advisory only)

**`src/` — Lean already. Ship.** 259 lines across `RSendsRouter.sol` (127) + `RSendsSplitRouter.sol` (132); every external function has a verified live caller (web `usePayFlow`/`useHostedCheckout` incl. both permit paths, `SetFeeConfig.s.sol`); every import used; comments carry load-bearing invariants (split math mirrored in backend `split_math`, fee semantics). Nothing to cut, nothing speculative.

- `packages/contracts/archive/:L1`: [contract] ~8,300 lines of retired Solidity (FeeRouter V1-V6, BatchDistributor, CCIP, Forwarder, Tron) kept in-package. Advisory: confirm `foundry.toml` excludes `archive/` from build/test runs so audit tooling and CI never compile it; DEPRECATED.md already documents the lineage. Not a cut here.
- `packages/contracts/DEPRECATED.md`: [contract] unfixed LOW finding F-SC-01 on FeeRouterV3 (testnet-only, superseded). Route to the RPagos audit as context; no action in this repo.
- `packages/contracts/broadcast/`: [contract] informational — no mainnet broadcast artifacts exist for the current `src/` routers (only anvil E2E + Base Sepolia dry-run), consistent with "mainnet routers undeployed". For the audit's deployment-provenance section.
- Cross-repo note: the only stale ABI coupling found points at the archive, not src (`apps/web/lib/usePermit2Flow.ts:277` calls `transferWithPermit2`, a FeeRouterV3/V4-only function — that hook is a dead-code delete in Area 2).

**net: 0 lines (advisory only by guardrail).**

---

## Out-of-scope notes (correctness / security / perf — for a normal review, NOT ponytail findings)

1. **`payment_indexer.py:L152/L183`** — if the eth-utils import fallback ever fired, the sentinel topic `"0xUNRESOLVED_RECOMPUTE_TOPIC"` would make the getLogs filter match nothing: the indexer would run "healthy" while detecting zero payments. Fail-silent; a raise would be fail-loud.
2. **`circuit_breaker.py:L255`** — `_get_redis()` does a fresh `get_redis()` + `ping()` on every `check()`/`record_success()`/`record_failure()` — up to 3 extra Redis round-trips per guarded RPC call, on the indexer's 5s tick.
3. **`aml_service.py:L342`** — `_check_structuring` returns `True` (structuring detected) when its DB query FAILS: an infra outage silently becomes a false `structuring` AMLAlert against the sender, with no error log.
4. **`webhook_service.py:L1444 vs L1032`** — `send_webhook` claims the Redis idempotency key (SETNX, 7-day TTL) BEFORE the DB delivery row is flushed; a post-claim rollback suppresses legitimate retries of that event for up to 7 days. The indexer's unfired-webhook sweep re-drives `payment.completed` only — other event types have no re-driver. (Related to the known "lost completed-webhook on transient dispatch failure" follow-up.)
5. **`middleware/rate_limit.py:L424`** — for `api_key`-keyed rules, unauthenticated requests fall back to `api_key_id = token[:24]` from the raw Authorization header: rotating garbage bearer prefixes yields a fresh sliding window per prefix on merchant endpoints (auth still rejects; the limiter is bypassable pre-auth). Consider keying unauthenticated traffic by IP.
6. **`security/api_keys.py:L183-199`** — the v1→v2 auto-upgrade writes `key_prefix` and commits even if bcrypt hashing failed inside the try (only hash assignments guarded); a half-upgraded row would then match Path 1 with no `key_hash_v2`. Low risk (v1 rows likely nonexistent).
7. **`main.py:L164-167`** — Celery liveness probed only at boot; a worker appearing after boot means Celery beat AND the asyncio fallback both run the same webhook/expiry jobs concurrently (idempotency of `process_pending_deliveries` becomes load-bearing).
8. **`config.py:L405`** — `EMAIL_DEV_MODE` prod guard keys on `ENVIRONMENT=production` while every other guard uses `is_prod_posture` (documented as intentional; single divergence from the H6 rule).
9. **Web: `app/api/tokens-market` + `app/api/market/[...path]`** — public unauthenticated CoinGecko proxies with in-process caching only; if the markets pages are kept, these need per-IP rate limiting (the backend mandates it for public endpoints; the web routes have no equivalent).
10. **Web: anti-phishing feature silently broken** — setup modal unopenable since the landing rewrite while `logoutClient.ts` still clears its key (see top-section finding; product decision).
11. **Web: `providers.tsx`** mounts Solana+Tron provider stacks and registers 13 adapters on every marketing page for a widget that never renders — dead-weight JS and third-party wallet probing.
12. **Web: `contractRegistry.ts:L247`** ships `https://eth-mainnet.g.alchemy.com/v2/demo` as mainnet rpcUrl (rate-limited demo endpoint); the landing widget inlines `NEXT_PUBLIC_ALCHEMY_API_KEY`/`NEXT_PUBLIC_INFURA_API_KEY` into client RPC URLs (dev Alchemy key already dead/401 per memory). Both moot after the cuts — then clean the env vars from Vercel.
13. **Web: `FooterGlobe.tsx`** hardcodes `mailto:emiliocatteddu@gmail.com`, `discord.gg/rsends`, `t.me/Emicatte26` — content ownership check before a business demo.

---

## Totals

| Area | net possible | of which [safe] |
|---|---|---|
| services/backend | ~-5,800 lines (+~420 test lines for deleted surfaces) | ~-2,150 |
| apps/web | ~-6,900 (→ ~-7,900 with markets cluster) | ~-5,800 |
| packages/contracts | 0 (advisory) | — |
| **Monorepo** | **~-12,700 lines** | **~-7,950** |

Suggested first `/ponytail` slice (highest value, lowest risk): the 12 backend whole-module deletes tagged [safe] + the web dead-cluster ([safe] items only), with characterization smoke tests where marked untested. Everything [verify] waits for its named confirmation.
