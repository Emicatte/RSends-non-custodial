# Discovery report — new-account login failure + silent login errors (2026-07-24)

Scope: the two production observations on `demo.rsends.io` — (1) a Safari-created account could not
log in right after signup (button loads briefly, re-enables, **no error, indefinitely**; same
credentials worked later on Chrome, where KYB was then completed); (2) console line
`GET /api/backend/api/v1/user/onboarding 401` after page load.

Method: full source trace (file:line cited throughout) + live reproduction on the local dev stack
(backend `uvicorn` on :8000 against local Postgres/Redis, `next dev` on :3000, Chromium via
Playwright). **No source changes, no prod mutations, no prod test accounts.** Every status code
below was captured live unless marked *(code-cited)*.

---

## 1. Verdict on the two hypotheses

### Hypothesis (b) — "login rejected for unapproved / pending-KYB account" — **REFUTED**

- **Source:** `POST /api/v1/auth/login` (`services/backend/app/api/auth_email_routes.py:150-209` →
  `app/services/email_auth_service.py:270-362`) contains **no approval branch and no
  email-verification branch**. Approval status is never read at login, refresh, or `/auth/me`.
- **Reproduced:** fresh signup (`201`) → immediate login **`200`** with a full session
  (access token + `rsends_refresh`/`rsends_sid` cookies), while the org was
  `approval_status="pending_approval"`. After approving the org via `/admin/approvals/{id}/approve`,
  login is byte-identical — approval changes nothing at the login endpoint.
- **Prod timeline agrees:** the account's KYB was completed *on Chrome after logging in there*,
  i.e. login succeeded in production while the account was still pending approval.

### Hypothesis (a) — "login succeeds, a post-login call 401s, the app bounces back silently" — **CONFIRMED as the mechanism**

The complete silent bounce loop was reproduced end-to-end, including the exact console line from
the prod report. What remains unconfirmed is only the **backend-side trigger** of the 401 in prod
(§3) — the frontend machinery that turns that 401 into a silent, indefinitely-retryable return to
the login page is proven.

**Reproduction F1b (dead backend session, prod path).** Log in (all 200s), then delete the
`auth:session:{sid}` keys from Redis (simulating backend-side session loss), then navigate to
`/en/onboarding` (the page the post-signup flow targets — see §2):

```
GET  /en/onboarding                              (Next RSC, session cookie valid)
GET  /api/backend/api/v1/user/onboarding -> 401   ← the console line observed in prod
POST /api/rp-auth/api/v1/auth/refresh    -> 401
POST /api/auth/signout                   -> 200   ← performLogout, automatic
NAV  /en/login?redirect=/onboarding               ← SILENT. No message. ~250 ms total.
```

Same result via `/en/app` (F1): guard 401 → `BackendUnreachableGate` probe 401 → refresh 401 →
signout → silent `router.replace('/login')`. In both cases the login page renders pristine
("Welcome back… Log in"), the button is enabled, and **no error is shown anywhere**. If the
backend keeps rejecting fresh sessions, every retry loops identically — matching
"clickable again, indefinitely, with no error message".

Chain (all verified in source AND live):
1. `LoginForm` (`apps/web/components/auth/LoginForm.tsx:79-103`): POST
   `/api/rp-auth/api/v1/auth/login` → `signIn('credentials')` (NextAuth `authorize` verifies the
   token server-to-server against `/api/v1/auth/me`, `lib/auth-options.ts:29-62`) →
   `router.push(redirect ?? /{locale}/app)`.
2. On `/en/onboarding`: `useOnboarding` (`hooks/useOnboarding.ts:39-57`) → `apiCall` 401 →
   one-shot refresh (`lib/auth-client.ts:71-106`); refresh 401/403 →
   `performLogout({skipBackend:true})` + `session_expired`.
3. `OnboardingGatePage` (`app/[locale]/onboarding/page.tsx:26-30`): `performLogout` flips
   `useSession` to `unauthenticated` → `router.replace('/login?redirect=/onboarding')` — the
   error branch (`setError(true)`) is set but the redirect wins the race; nothing renders.
4. On `/en/app`: `enforceOnboarding` (`lib/onboarding-guard.ts:69-71`) resolves `'stale-token'` on
   401 → `BackendUnreachableGate` (`components/app/BackendUnreachableGate.tsx:123-127`) probes,
   and on `session_expired`/401 does a **silent `router.replace('/login')`** by design.

**Happy-path control (no failure injected).** Fresh signup on Chromium: signup `201` →
`SignupForm` pushes `/en/onboarding` → middleware (`middleware.ts:52-59`, no session) redirects to
**`/en/login?redirect=%2Fen%2Fonboarding`** — this is how the prod user "was returned to login"
(it's by design; signup does not auto-login, `auth_email_routes.py:139-147`). Login → `200`,
callback `200`, onboarding `200` (`approval_status:"pending_approval"`) → routed to
`/en/onboarding/company`. **A brand-new unapproved account logs in cleanly** when the backend
honors its session. The defect is not in the login flow's logic.

---

## 2. What triggered the 401 in production (unconfirmed — candidates + discriminators)

The frontend loop is proven; the open question is why the prod backend rejected a Bearer token
seconds after minting it (it had just passed `/auth/me` inside `signIn`). Token verification is
JWT-decode **plus a Redis liveness check** on `auth:session:{sid}`
(`app/services/auth_service.py:67-94`); the 401 `detail.code` names the reason.

| Candidate | Fits the evidence? | Discriminator (backend/Render logs) |
|---|---|---|
| **(iii) Backend session died in Redis right after creation** (eviction under memory pressure on the Render Key-Value instance, restart/failover, `maxmemory` policy) | **Best fit.** Explains: login 200, `/auth/me` 200, next call 401, refresh 401, loop on every retry during the bad window, and Chrome working hours later (transient condition — the "browser difference" would be timing, matching the user's own suspicion that the browser is not the cause). Exact mechanics reproduced in F1/F1b. | 401 body `{"detail":{"code":"session_revoked"}}` on `/api/v1/user/onboarding`, refresh `session_revoked`/`no_session`; Redis eviction/restart metrics at the incident time |
| (ii) Safari never stored `rsends_refresh`/`rsends_sid` | **Cannot alone cause this.** The probe uses the Bearer token (valid 15 min) — missing refresh cookies only bite after token expiry. Could only *combine* with (iii) to make refresh fail as `no_session` instead of `session_revoked`. Cookies carry no `Domain` attribute and the Path rewrite (`app/api/rp-auth/[...path]/route.ts:47-55`) is correct — verified stored in the local run. | refresh 401 code: `no_session` (cookies never arrived) vs `session_revoked` (arrived, session dead) |
| (iv) Tokenless probe (`session.access_token` undefined → request sent with no `Authorization`) | Only reachable via `/en/app` (`BackendUnreachableGate` probes with whatever `tokenRef` holds); on `/en/onboarding`, `useOnboarding.reload` guards on `!tokenRef.current` and instead **hangs on the loading copy forever** (`hooks/useOnboarding.ts:40-45` — separate defect, §5). No known way for the credentials flow to omit `access_token` from the JWT (`lib/auth-options.ts:73-85`). | 401 body `{"detail":{"code":"no_token"}}` |
| (i) NextAuth session cookie never stored (pure middleware bounce) | **Contradicted by the console line**: the `/api/backend/...onboarding` probe only runs with an authenticated NextAuth session. | n/a |

**Prod log evidence was not obtainable in this session:** the Render MCP connection is
unauthorized (needs re-auth), and Vercel runtime-log retention doesn't reach back to the incident —
the last 24 h of production requests are **all 200/307/404, zero 401s** (which also says the
failure state is not currently active). The schema CSVs in the repo root carry no row data.
**One Render query closes this:** backend request logs for `GET /api/v1/user/onboarding` → the 401
`detail.code` (`session_revoked` vs `no_session` vs `no_token` vs `invalid_token`) at the incident
time, plus the Key-Value instance's memory/eviction/restart metrics. The `user_sessions` audit
table (`auth_email_routes.py:172-182`) will also show the Safari logins' `created_at`/UA rows —
each 200 login persisted one — confirming how many times the loop ran.

---

## 3. Approval-gate enforcement map (Part 1, Q3)

| Point | Enforces approval? | Behavior for unapproved account |
|---|---|---|
| `POST /api/v1/auth/login` | **No** | 200 + full session (reproduced) |
| `POST /api/v1/auth/refresh` (`app/api/auth_routes.py:98-167`) | **No** | 200 rotation |
| `GET /api/v1/auth/me` | **No** | 200 |
| `GET /api/v1/user/onboarding` (`app/api/user_onboarding_routes.py:94-104`) | **No** — it *reports* state | 200 with `approval_status:"pending_approval"` (reproduced); 401 `no_token`/`invalid_token` without a valid session (reproduced) |
| `require_org_approved` (`app/api/deps/require_org_approved.py:40-74`) — session org routes | **Yes** | 403 `company_profile_required` / `approval_pending` / `approval_declined` |
| `require_approved_merchant` (`app/api/deps/require_approved_merchant.py`) — API-key surface | **Yes** | 403 `approval_pending` / `approval_declined` |
| Frontend | Routing only | `resolveOnboardingRedirect` sends pending accounts to `/onboarding/pending` (never blocks login) |

Login failure branches (all `{"detail":{"code":…,"message":…}}`, `auth_email_routes.py:57-86`):
401 `invalid_credentials` (unknown email / wrong password — reproduced), 403 `password_not_set`,
403 `account_suspended`, 410 `account_deleted`, 429 `rate_limit_exceeded` (service level:
5/15 min per IP, 10/h per email, `email_auth_service.py:285-291`), plus an **uncaught 500** when
Redis is down at `create_session` (§6.2). Success: 200 `{access_token (15-min JWT), …}` +
`Set-Cookie rsends_refresh`/`rsends_sid` (HttpOnly, Secure, SameSite=strict,
`Path=/api/v1/auth`, 7 d, no Domain — `auth_email_routes.py:89-109`). Cookies travel via the
same-origin `/api/rp-auth` proxy (Path rewritten to its mount); nothing on the auth path is
cross-site in the browser — cookie mechanics are **not implicated** (Part 1, Q5), consistent with
the account working from Chrome.

---

## 4. Part 2 — inventory of silent / degraded failure branches

### 4.1 Login form (`LoginForm.tsx` + `EmailAuthError.tsx`)

| Backend outcome | UI rendered | Verdict |
|---|---|---|
| 401 `invalid_credentials` | "Email or password is incorrect.", button re-enabled | OK (reproduced) |
| 429 `rate_limit_exceeded` | localized card + retry-in suffix *(code-cited; keys exist ×5 locales)* | OK |
| 403 `password_not_set` / `account_suspended` / 410 `account_deleted` | localized cards *(code-cited)* | OK |
| 403 `approval_pending` / `approval_declined` (would come from other routes; login never emits them) | falls to generic "unknown" — **keys missing in all 5 locales** | Degraded |
| 5xx / proxy 502 (backend down) | "Something went wrong. Please try again." (reproduced, F3a) | Visible but uninformative |
| Network error (fetch throws) | raw unlocalized `TypeError` text ("Failed to fetch"/"Load failed") — `LoginForm.tsx:98-99` passes the exception as the error shape; no `network_error` key exists | Degraded |
| `signIn` fails (`/auth/me` unreachable or rejects) | hard-coded **"Email or password is incorrect."** (`LoginForm.tsx:92-94`) — misattributes an infra failure to the user's password | Misleading |
| **Success → post-login bounce (the prod case)** | **Nothing. Silent return to a pristine login page** (reproduced, F1/F1b) | **Silent — the defect** |

The form itself always renders *something* on a direct failure; every fully-silent branch is
post-login:

- `BackendUnreachableGate.tsx:123-127` — 401/`session_expired` → `router.replace('/login')`, no
  message, no query param. (Reproduced.)
- `OnboardingGatePage` (`onboarding/page.tsx:26-30`) — post-logout `unauthenticated` →
  `router.replace('/login?redirect=/onboarding')`, wins the race against its own error card.
  (Reproduced.)
- `middleware.ts:52-59` — no NextAuth token on a dashboard path → redirect to
  `/login?redirect=…`, messageless (correct for a signed-out visitor, but it's also the landing
  of every forced logout).
- Note: **`auth.errors.session_expired` copy already exists in all 5 locales** — it is simply
  never displayed by any of these paths.

### 4.2 Locale coverage (Part 2, Q7)

Verified across `messages/{de,en,es,fr,it}.json`: the `auth.errors` key set is **identical in all
five** — no per-locale drift. Present everywhere: `invalid_credentials`, `rate_limit_exceeded`,
`unknown`, `session_expired`, `auth_unavailable`, `password_not_set`, `account_suspended`,
`account_deleted`, `email_not_verified`, `turnstile_failed`. **Missing everywhere:**
`approval_pending`, `approval_declined`, any network-error key.

### 4.3 App shell with the backend unreachable (Part 2, Q8)

Reproduced (F3b): authed `/en/app` with the backend stopped → proxy synthesizes
`502 BACKEND_UNREACHABLE` → `BackendUnreachableGate` renders a **textless pulsing skeleton**
(`aria-busy`, zero words on screen) for the full retry budget —
`RETRY_DELAYS_MS` ≈ 90 s (+ up to 6×5 s rechecks) — before the first visible error card
(observed 54 s of pure skeleton; card copy exists at `onboarding.gate.unreachable.*` ×5 locales).
The login page during the same outage shows the generic "Something went wrong" card immediately
(F3a). The `/onboarding` gate page shows a visible error + retry (`onboarding.gate.error`)
*(code-cited)*.

---

## 5. Proposed scoped fixes (NOT implemented — discovery only)

**Problem 1 — the silent bounce loop (prod incident).**
1. *Surface the reason on every forced return to login.* `BackendUnreachableGate` and the
   `OnboardingGatePage` unauthenticated-redirect should replace to
   `/login?error=session_expired`; `LoginForm` reads the param once and renders the existing
   `auth.errors.session_expired` copy (already translated ×5). One-line changes at
   `BackendUnreachableGate.tsx:126`, `onboarding/page.tsx:28`, plus a param read in
   `LoginForm.tsx`. This converts the loop from invisible to self-explanatory regardless of the
   backend trigger.
2. *Close the backend trigger* once discriminated (one Render log query, §2): if it is Redis
   session loss, that is an ops fix (Key-Value sizing/eviction policy + the existing
   `auth_unavailable` 503 path already fails closed) — plus optionally distinguishing
   `session_revoked` copy ("your session expired, please log in again") from a credentials error.
3. *(Related hardening, small):* `useOnboarding.ts:40-45` — when `status==='authenticated'` but
   the token never arrives, resolve to an error state after a timeout instead of `loading=false,
   error=false, state=null`, which leaves the gate page on its loading copy forever.

**Problem 2 — silent/degraded login-form branches.**
1. Map network failures: catch `TypeError` in `LoginForm.onSubmit` → `code:'network_error'` + add
   the key ×5 locales (currently renders the raw browser message).
2. Stop hard-coding `invalid_credentials` on `signIn` failure (`LoginForm.tsx:92-94`): a `signIn`
   error after a 200 from `backendLogin` is infrastructural — render `unknown`/`auth_unavailable`
   copy instead.
3. Add `approval_pending`/`approval_declined` to `auth.errors` ×5 locales (defense in depth for
   any future 403 surfaced to this form).
4. Backend-down shell: show an interim "connecting to the server…" line on the
   `BackendUnreachableGate` skeleton (copy slot already exists under `onboarding.gate.*`) so the
   90-second wait is not wordless.

---

## 6. Additional defects flagged separately (not folded into the two above; do not drive-by fix)

1. **Phantom `email_verified_gate`.** Docstrings (`user_onboarding_routes.py:6-11`,
   `email_auth_service.py:317-322`) describe a deny-by-default middleware returning 403
   `email_not_verified`; **no such middleware or dependency exists** in the codebase. In prod
   posture (signup leaves `email_verified=False`) nothing enforces verification — only the
   independent approval gate. Docs/code divergence with a security-posture claim.
2. **Login 500 (not 503) on Redis outage.** `login()` → `create_session` raises
   `AuthError("auth_unavailable")` (`auth_service.py:135-136`); the route catches only
   `EmailAuthError` (`auth_email_routes.py:168-169`) → unhandled 500. Refresh/`me` translate the
   same error to 503.
3. **Shared default rate bucket for the whole auth surface.** `/api/v1/auth/login|signup|verify-email|reset…`
   have no `ENDPOINT_LIMITS` entries; they share one `rl:ip:{ip}:POST:/api/v1/auth` bucket at
   30/min (`app/middleware/rate_limit.py:433` + `DEFAULT_POST_LIMIT`), on top of the
   service-level limits. Burst on one endpoint starves the others; the two layers also emit two
   different 429 body shapes.
4. **`require_approved_merchant` conflates "no resolvable org" with "pending"** — a live merchant
   key whose owner address resolves to 0 or ≥2 orgs gets 403 `approval_pending`
   (`require_approved_merchant.py:73-75`), undiagnosable from the outside.
5. **Gate-page loading hang** on authenticated-but-tokenless sessions (see fix 1.3).
6. **Dev-environment gaps found while reproducing** (local only, no prod impact):
   `scripts/gen_dev_env.py` writes neither `NEXT_PUBLIC_WC_PROJECT_ID` nor `TURNSTILE_SECRET_KEY`
   into `apps/web/.env.local` — without the first, `/en/signup` and `/en/login` **crash client-side**
   (RainbowKit "No projectId found", empty page); without the second, `POST /api/auth/signup`
   fail-closes with 500 `turnstile_unconfigured`, so local UI signup is impossible out of the box
   (Cloudflare's always-pass test keys `1x00000000000000000000AA` /
   `1x0000000000000000000000000000000AA` work for dev). Also `services/backend/venv` has stale
   shebangs from the repo's old path (`~/Desktop/wallet-connect/…`) — `venv/bin/uvicorn` is dead;
   `venv/bin/python -m uvicorn` works.

---

## 7. Reproduction appendix (exact captured statuses)

Server-side, fresh account pre-approval (curl → :8000):
`POST /auth/signup` **201** (`email_verified:true` — dev posture) → `POST /auth/login` **200**
(token + both cookies) → `GET /user/onboarding` **200** `pending_approval` → `GET /auth/me`
**200** → `POST /auth/refresh` **200** (rotation) → controls: onboarding no-token **401
`no_token`**, garbage token **401 `invalid_token`**, refresh without cookies **401 `no_session`**,
wrong password **401 `invalid_credentials`**. Admin approve **200** → login/onboarding identical
but `approved`.

Browser (Chromium 1228, `next dev`): happy path in §1; F1/F1b (session killed in Redis) in §1/§2;
F3a/F3b (backend stopped) in §4.3. Scripts:
`scratchpad/repro_signup_login.js`, `forced_failure_f1{,b}.js`, `forced_failure_f3.js` (session
scratchpad, not part of the repo). Safari-specific cookie storage was not testable locally
(backend cookies are unconditionally `Secure`; Safari rejects Secure cookies on plain-http
localhost — would need an https dev origin), but §2 shows cookie storage cannot produce the
observed console line anyway.
