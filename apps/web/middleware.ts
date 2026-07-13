import { NextRequest, NextResponse } from 'next/server'
import createIntlMiddleware from 'next-intl/middleware'
import { getToken } from 'next-auth/jwt'
import { routing } from './i18n/routing'

const COOKIE_NAME = 'admin_session'

const intlMiddleware = createIntlMiddleware(routing)

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // ── Admin auth guard (unchanged) ──────────────────────
  if (pathname.startsWith('/admin') && pathname !== '/admin/login') {
    const session = req.cookies.get(COOKIE_NAME)?.value
    if (!session) {
      const loginUrl = req.nextUrl.clone()
      loginUrl.pathname = '/admin/login'
      return NextResponse.redirect(loginUrl)
    }
    return NextResponse.next()
  }

  // ── Auth-aware routing ─────────────────────────────────
  // Dashboard areas (/app, /settings) require a session; core marketing and
  // auth pages bounce authenticated users into the dashboard (Stripe-style
  // app/marketing separation). Paths are localized (/en/app, /it/login, ...).
  const segments = pathname.split('/')                      // '/en/app/x' → ['','en','app','x']
  const maybeLocale = segments[1] ?? ''
  const hasLocale = (routing.locales as readonly string[]).includes(maybeLocale)
  const locale = hasLocale ? maybeLocale : routing.defaultLocale
  const bare = hasLocale ? '/' + segments.slice(2).join('/') : pathname

  const isDashboard =
    bare === '/app' || bare.startsWith('/app/') ||
    bare === '/settings' || bare.startsWith('/settings/') ||
    // Onboarding wizard: session-required like the dashboard (no-token →
    // login; unverified → verify page), but NOT in AUTHED_BOUNCE — authed
    // users must be able to sit on it. The consent/company gating itself is
    // server-side in the /app and /settings layouts (lib/onboarding-guard).
    bare === '/onboarding' || bare.startsWith('/onboarding/')

  // Only locale-prefixed URLs bounce: a bare '/' or '/login' first passes
  // through intlMiddleware's locale negotiation (/ → /it), then bounces on
  // that second, prefixed request — keeping the negotiated locale.
  const AUTHED_BOUNCE = ['/', '/how-it-works', '/pricing', '/team', '/vision', '/login', '/signup']
  const isBouncePath = hasLocale && AUTHED_BOUNCE.includes(bare)

  if (isDashboard || isBouncePath) {
    const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET })

    if (isDashboard) {
      // (a) Not logged in → /login with ?redirect=<full path> to return after login.
      if (!token) {
        const url = req.nextUrl.clone()
        url.pathname = `/${locale}/login`
        url.search = ''
        url.searchParams.set('redirect', pathname)          // encoded automatically
        return NextResponse.redirect(url)
      }

      // (b) Logged in but email EXPLICITLY unverified → verify page. A legacy
      //     token without the claim leaves email_verified === undefined →
      //     must NOT block (only an explicit false does).
      if (token.email_verified === false) {
        const url = req.nextUrl.clone()
        url.pathname = `/${locale}/verify-email-sent`
        url.search = ''
        return NextResponse.redirect(url)
      }

      // (c) Authenticated (verified, or legacy-undefined) → continue via intl middleware.
      //     Never NextResponse.next(): with next-intl v4 (and no setRequestLocale in the
      //     project) the middleware is what communicates the locale to getMessages();
      //     bypassing it would render /it/app in English. intlMiddleware passes
      //     already-prefixed paths through without redirecting.
      return intlMiddleware(req)
    }

    // Marketing/auth page + authenticated → dashboard. Unverified users are
    // deliberately NOT bounced: they still need /login and the marketing pages,
    // and bouncing them would ping-pong via the verify-email-sent redirect in
    // (b). An authed user on /login?redirect=X goes to /app (param dropped).
    if (token && token.email_verified !== false) {
      const url = req.nextUrl.clone()
      url.pathname = `/${locale}/app`
      url.search = ''
      return NextResponse.redirect(url)
    }
    return intlMiddleware(req)
  }

  // ── i18n routing for everything else ──────────────────
  return intlMiddleware(req)
}

export const config = {
  // Match everything EXCEPT: /api, /admin, /merchant, /pay, /tokens, /docs, /_next, static files.
  // /docs is the English-only, next-intl–excluded docs site (served at /docs/* with no locale
  // prefix). Excluding it here stops the locale redirect; the localized legal pages still live at
  // /{locale}/docs/* (those start with a locale segment, so they remain matched).
  matcher: [
    '/((?!api|_next|admin|merchant|pay|tokens|docs|_vercel|.*\\..*).*)',
  ],
}
