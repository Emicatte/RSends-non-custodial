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

  // ── User dashboard guard (/settings) ──────────────────
  // The OAuth/session area is now /settings (the Classic /app consumer dashboard
  // was archived). Paths are localized (/en/settings, /it/settings, ...).
  const segments = pathname.split('/')                      // '/en/settings/x' → ['','en','settings','x']
  const maybeLocale = segments[1] ?? ''
  const hasLocale = (routing.locales as readonly string[]).includes(maybeLocale)
  const locale = hasLocale ? maybeLocale : routing.defaultLocale
  const bare = hasLocale ? '/' + segments.slice(2).join('/') : pathname

  if (bare === '/settings' || bare.startsWith('/settings/')) {
    const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET })

    // (a) Non loggato → /login con ?redirect=<path completo> per tornare dopo il login.
    if (!token) {
      const url = req.nextUrl.clone()
      url.pathname = `/${locale}/login`
      url.search = ''
      url.searchParams.set('redirect', pathname)            // encoding automatico
      return NextResponse.redirect(url)
    }

    // (b) Loggato ma email ESPLICITAMENTE non verificata (solo credentials) → verify page.
    //     OAuth (Google/GitHub) lascia email_verified === undefined → NON deve bloccare.
    if (token.email_verified === false) {
      const url = req.nextUrl.clone()
      url.pathname = `/${locale}/verify-email-sent`
      url.search = ''
      return NextResponse.redirect(url)
    }

    // (c) Autenticato (+ verificato, oppure OAuth-undefined) → prosegui con l'intl middleware.
    //     NON usare NextResponse.next(): con next-intl v4 (e senza setRequestLocale nel progetto)
    //     è il middleware a comunicare il locale a getMessages(); bypassarlo farebbe renderizzare
    //     /it/app in inglese. intlMiddleware lascia passare i path già prefissati senza redirect.
    return intlMiddleware(req)
  }

  // ── i18n routing for landing pages ────────────────────
  return intlMiddleware(req)
}

export const config = {
  // Match everything EXCEPT: /app, /api, /admin, /_next, static files
  matcher: [
    '/((?!api|_next|admin|merchant|pay|tokens|_vercel|.*\\..*).*)',
  ],
}
