---
name: verify
description: Drive the authed /app dashboard locally (no real backend) to visually verify web UI changes — stub backend + forged NextAuth cookie + Playwright screenshots.
---

# Verifying apps/web UI changes (incl. the session-gated /app dashboard)

The /app dashboard is gated by `getServerSession` + `enforceOnboarding` (a
server-side fetch to `RPAGOS_BACKEND_URL/api/v1/user/onboarding`). You can
drive the whole surface locally without the Python backend:

## Recipe

1. **Stub backend** — a plain node `http` server on `127.0.0.1:4545` serving
   the JSON the pages read. ALL browser traffic goes through the Next proxy
   `/api/backend/{path}` → `RPAGOS_BACKEND_URL/{path}`, so one stub covers
   everything (zero CORS). Endpoints the dashboard needs:
   - `GET /api/v1/user/onboarding` → fully-onboarded state
     (`consents_current/age_attested/email_verified: true`,
     `onboarding_status: 'company_submitted'`, `approval_status: 'approved'`)
   - `GET /api/v1/organizations` → `{ organizations: [...], active_org_id }`
   - `GET /api/v1/user/org/stats` → `OrgStats` (hooks/useOrgStats.ts)
   - `GET /api/v1/user/org/payment-intents` → `{ total, page, per_page, records }`
     (hooks compute has_prev/has_next from `total` and PER_PAGE=20 — set
     `total > 20` to make pagination render)
   - `GET /api/v1/user/org/webhooks` → `{ total, records }` (NOT a bare array —
     the page crashes on `webhooks.length` if the shape is wrong)
   - `GET /api/v1/user/org/merchant-keys` → `{ keys: MerchantKeyItem[] }`
     (field is `prefix`, not `key_prefix`)
   - `GET /api/v1/user/api-keys` → `{ keys, max_allowed, remaining_slots }`
   - Expect 404 noise from `GET /api/v1/user/{contacts,transactions}` — the
     dormant custodial listeners mounted in the /app layout (known residue,
     harmless).

2. **Forge a session cookie** with the app's own next-auth (v4) and the local
   `NEXTAUTH_SECRET` from `apps/web/.env.local`:
   ```js
   const { createRequire } = require('module')
   const webRequire = createRequire('<apps/web>/package.json')
   const { encode } = webRequire('next-auth/jwt')
   const jwt = await encode({ token: { sub: 'user_1', name: 'Test', email: 't@example.test', access_token: 'stub-access-token' }, secret, maxAge: 3600 })
   ```
   Set it as cookie `next-auth.session-token` on `127.0.0.1` (no `__Secure-`
   prefix on http). The `access_token` value is opaque to the web app — the
   stub ignores Authorization anyway.

3. **Launch** the dev server with the stub as backend:
   ```bash
   RPAGOS_BACKEND_URL=http://127.0.0.1:4545 NEXT_PUBLIC_RPAGOS_BACKEND_URL=http://127.0.0.1:4545 \
   NEXTAUTH_URL=http://127.0.0.1:3100 npx next dev -p 3100
   ```
   Shell env overrides `.env.local`. Routes are locale-prefixed: `/en/app`,
   `/en/app/payments`, `/en/app/webhooks`, `/en/app/api-keys`.
   Sanity: `curl` `/en/app` without the cookie → 307 (login redirect); with
   it → 200.

4. **Drive + capture** with Playwright (install in the scratchpad, not the
   repo). Screenshot each page at 1440/1280/375. A `page.evaluate` geometry
   probe (main/aside/nav/h1 `getBoundingClientRect`) catches alignment bugs
   screenshots hide — e.g. topbar-vs-content x-offset when max-w binds.

## Gotchas

- Jest suites live in `app/__tests__/` — they key on text/roles/testids, not
  spacing, so they don't substitute for visual verification.
- `apps/web/global.css` (root) was a dead orphan (deleted 2026-07-15); only
  `app/globals.css` is imported. Check imports before trusting any stylesheet.
- Kill the dev server and stub when done; both bind fixed ports (3100/4545).
