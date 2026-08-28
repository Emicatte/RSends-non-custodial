/**
 * @jest-environment node
 *
 * The four server-side doors that send an unauthenticated visitor away.
 *
 * Client-side bounces have carried `?error=session_expired` since PR #74 and
 * render a message. These four carried nothing, which is how the 2026-08-26
 * incident presented: sign-in succeeded, the session did not settle, and the
 * user was returned to a pristine form with no reason given.
 *
 * Every one of them must now name a reason, and must not lose where the user
 * was going. `/settings` is the worst of the four today — it bounces to the
 * marketing home page, so the user does not even land somewhere they can act.
 */

import { NextRequest } from 'next/server'

const mockGetToken = jest.fn()
const mockGetServerSession = jest.fn()

jest.mock('next-auth/jwt', () => ({
  getToken: (...args: unknown[]) => mockGetToken(...args),
}))

jest.mock('next-auth', () => ({
  getServerSession: (...args: unknown[]) => mockGetServerSession(...args),
}))

// The real one throws to halt rendering; mirror that so control flow matches.
jest.mock('next/navigation', () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`)
  },
}))

jest.mock('next-intl/middleware', () => ({
  __esModule: true,
  default: () => () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { NextResponse } = require('next/server')
    return NextResponse.next()
  },
}))

jest.mock('next-intl/server', () => ({
  getTranslations: async () => (k: string) => k,
}))

// next-intl ships untransformed ESM; the middleware only reads these two.
jest.mock('@/i18n/routing', () => ({
  routing: {
    locales: ['en', 'it', 'es', 'fr', 'de'],
    defaultLocale: 'en',
    localePrefix: 'always',
  },
}))

// Heavy client subtrees below the redirect — never reached, but their module
// graph would load in this environment.
jest.mock('@/lib/onboarding-guard', () => ({ enforceOnboarding: jest.fn() }))
jest.mock('@/lib/auth-options', () => ({ authOptions: {} }))
jest.mock('@/components/app/BackendUnreachableGate', () => ({
  BackendUnreachableGate: () => null,
}))
jest.mock('@/components/app/AppNav', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/app/AppSidebar', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/app/AppBottomNav', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/app/AppTopbar', () => ({ __esModule: true, default: () => null }))
jest.mock('@/components/app/TestnetBanner', () => ({ TestnetBanner: () => null }))
jest.mock('@/components/settings/SettingsSidebar', () => ({ SettingsSidebar: () => null }))
jest.mock('@/components/settings/OrgSwitcher', () => ({ OrgSwitcher: () => null }))
jest.mock('@/components/auth/AuthHeader', () => ({ __esModule: true, default: () => null }))

beforeEach(() => {
  jest.clearAllMocks()
  process.env.NEXTAUTH_SECRET = 'test-secret'
})

/** Run a server layout with no session and return the URL it redirected to. */
async function bounceOf(
  layout: (args: {
    children: React.ReactNode
    params: Promise<{ locale: string }>
  }) => Promise<unknown>,
): Promise<string> {
  mockGetServerSession.mockResolvedValue(null)
  try {
    await layout({ children: null, params: Promise.resolve({ locale: 'en' }) })
  } catch (e) {
    const m = /^REDIRECT:(.*)$/.exec((e as Error).message)
    if (m) return m[1]
    throw e
  }
  throw new Error('layout did not redirect')
}

// ── door 1: middleware ───────────────────────────────────────────────────

it('middleware names a reason when bouncing an unauthenticated dashboard hit', async () => {
  mockGetToken.mockResolvedValue(null)
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { middleware } = require('@/middleware')

  const res = await middleware(new NextRequest('http://localhost/en/app/payments'))
  const location = new URL(res.headers.get('location') as string)

  expect(location.pathname).toBe('/en/login')
  expect(location.searchParams.get('error')).toBe('sign_in_required')
  expect(location.searchParams.get('redirect')).toBe('/en/app/payments')
})

it('middleware still bounces an authenticated visitor off /login, with no error param', async () => {
  mockGetToken.mockResolvedValue({ sub: 'u1' })
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { middleware } = require('@/middleware')

  const res = await middleware(new NextRequest('http://localhost/en/login'))
  const location = new URL(res.headers.get('location') as string)

  expect(location.pathname).toBe('/en/app')
  expect(location.searchParams.get('error')).toBeNull()
})

// ── doors 2-4: the server layouts ────────────────────────────────────────

it('the /app layout names a reason and keeps the destination', async () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const layout = require('@/app/[locale]/app/layout').default
  const url = new URL(await bounceOf(layout), 'http://localhost')

  expect(url.pathname).toBe('/en/login')
  expect(url.searchParams.get('error')).toBe('sign_in_required')
  expect(url.searchParams.get('redirect')).toBe('/en/app')
})

it('the /onboarding layout names a reason and keeps the destination', async () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const layout = require('@/app/[locale]/onboarding/layout').default
  const url = new URL(await bounceOf(layout), 'http://localhost')

  expect(url.pathname).toBe('/en/login')
  expect(url.searchParams.get('error')).toBe('sign_in_required')
  expect(url.searchParams.get('redirect')).toBe('/en/onboarding')
})

it('the /settings layout goes to login, not to the marketing home page', async () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const layout = require('@/app/[locale]/settings/layout').default
  const url = new URL(await bounceOf(layout), 'http://localhost')

  expect(url.pathname).toBe('/en/login')
  expect(url.pathname).not.toBe('/en')
  expect(url.searchParams.get('error')).toBe('sign_in_required')
  expect(url.searchParams.get('redirect')).toBe('/en/settings')
})
