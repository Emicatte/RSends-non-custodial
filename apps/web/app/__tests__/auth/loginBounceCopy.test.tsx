/**
 * What the login page SAYS when a server-side bounce lands on it.
 *
 * Background (2026-08-26 incident, cause A1): the backend authenticated, the
 * NextAuth session never settled in the browser, and the server-side bounces
 * returned the user to a pristine login form with no message at all. They were
 * left to guess. A browser that drops the session cookie loops forever.
 *
 * Contract:
 *  - `?error=sign_in_required` renders sign-in copy (all four bounces emit it);
 *  - `?error=session_expired` still renders the expired copy (pre-existing);
 *  - any other `?error=` value renders nothing — the param feeds a translation
 *    key, so the whitelist must stay a whitelist;
 *  - a successful login leaves a marker, and if the very next thing that
 *    happens is a `sign_in_required` bounce, the copy UPGRADES to
 *    session_not_persisted: sign-in worked, the browser did not keep it;
 *  - `session_not_persisted` is never accepted FROM the URL — only ever
 *    derived client-side;
 *  - a stale or missing marker leaves the generic copy standing, and blocked
 *    storage degrades to the generic copy rather than crashing or guessing.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'

const mockPush = jest.fn()
const mockSignIn = jest.fn()
let mockSearchParams = new URLSearchParams()

/** Contract values, pinned literally so a rename in the source is a failure. */
const MARKER_KEY = 'rsends:signed-in-at'
const MARKER_TTL_MS = 15_000

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    const t = (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
    ;(t as any).rich = (key: string) => t(key)
    return t
  },
  useLocale: () => 'en',
}))

jest.mock('next-auth/react', () => ({
  signIn: (...args: unknown[]) => mockSignIn(...args),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useSearchParams: () => mockSearchParams,
}))

jest.mock('@/hooks/useEmailAuth', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const actual = jest.requireActual('@/hooks/useEmailAuth')
  return {
    ...actual,
    useEmailAuth: () => ({
      signup: jest.fn(),
      checkEmail: jest.fn(),
      resendVerification: jest.fn(),
      loading: false,
      error: null,
      clearError: jest.fn(),
    }),
  }
})

import { LoginForm } from '@/components/auth/LoginForm'

// eslint-disable-next-line @typescript-eslint/no-require-imports
const en = require('@/messages/en.json')

beforeEach(() => {
  jest.clearAllMocks()
  mockSearchParams = new URLSearchParams()
  window.sessionStorage.clear()
  global.fetch = jest.fn() as unknown as typeof fetch
  jest.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  jest.restoreAllMocks()
})

function message(): string {
  return screen.getByTestId('auth-error-message').textContent ?? ''
}

// ── the whitelist ────────────────────────────────────────────────────────

it('renders the sign-in copy on ?error=sign_in_required', () => {
  mockSearchParams = new URLSearchParams('error=sign_in_required')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.sign_in_required)
})

it('still renders the expired copy on ?error=session_expired', () => {
  mockSearchParams = new URLSearchParams('error=session_expired')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.session_expired)
})

it('renders nothing for an ?error= value outside the whitelist', () => {
  mockSearchParams = new URLSearchParams('error=approval_pending')
  render(<LoginForm />)

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('never accepts session_not_persisted from the URL', () => {
  // Derived client-side only. Accepting it from the query string would let a
  // crafted link tell a user their browser is broken when it is not.
  mockSearchParams = new URLSearchParams('error=session_not_persisted')
  render(<LoginForm />)

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

// ── the upgrade: sign-in worked, the browser did not keep it ──────────────

it('upgrades to session_not_persisted when the bounce follows a fresh sign-in', () => {
  window.sessionStorage.setItem(MARKER_KEY, String(Date.now()))
  mockSearchParams = new URLSearchParams('error=sign_in_required')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.session_not_persisted)
  expect(message()).not.toBe(en.auth.errors.sign_in_required)
})

it('leaves the generic copy when the marker is stale', () => {
  window.sessionStorage.setItem(
    MARKER_KEY,
    String(Date.now() - MARKER_TTL_MS - 1_000),
  )
  mockSearchParams = new URLSearchParams('error=sign_in_required')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.sign_in_required)
})

it('leaves the generic copy when there is no marker', () => {
  mockSearchParams = new URLSearchParams('error=sign_in_required')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.sign_in_required)
})

it('does not upgrade session_expired — that bounce has its own cause', () => {
  window.sessionStorage.setItem(MARKER_KEY, String(Date.now()))
  mockSearchParams = new URLSearchParams('error=session_expired')
  render(<LoginForm />)

  expect(message()).toBe(en.auth.errors.session_expired)
})

it('consumes the marker so a later unrelated bounce is not upgraded', () => {
  window.sessionStorage.setItem(MARKER_KEY, String(Date.now()))
  mockSearchParams = new URLSearchParams('error=sign_in_required')
  const first = render(<LoginForm />)
  expect(message()).toBe(en.auth.errors.session_not_persisted)
  first.unmount()

  render(<LoginForm />)
  expect(message()).toBe(en.auth.errors.sign_in_required)
})

// ── the marker is written by a successful sign-in ────────────────────────

it('records the sign-in marker before navigating away', async () => {
  ;(global.fetch as unknown as jest.Mock).mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => ({
      access_token: 'tok',
      expires_in: 900,
      user_id: 'u1',
      email: 'user@example.com',
      email_verified: true,
    }),
  })
  mockSignIn.mockResolvedValue({ ok: true, error: undefined })
  render(<LoginForm />)

  fireEvent.change(screen.getByLabelText(en.auth.login.emailLabel), {
    target: { value: 'user@example.com' },
  })
  fireEvent.change(screen.getByLabelText(en.auth.login.passwordLabel), {
    target: { value: 'hunter2hunter2' },
  })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: en.auth.login.submit }))
  })

  expect(mockPush).toHaveBeenCalled()
  const marker = Number(window.sessionStorage.getItem(MARKER_KEY))
  expect(Number.isFinite(marker)).toBe(true)
  expect(Date.now() - marker).toBeLessThan(MARKER_TTL_MS)
})

it('does not record a marker when the sign-in failed', async () => {
  ;(global.fetch as unknown as jest.Mock).mockResolvedValue({
    ok: false,
    status: 401,
    headers: { get: () => null },
    json: async () => ({ detail: { code: 'invalid_credentials' } }),
  })
  render(<LoginForm />)

  fireEvent.change(screen.getByLabelText(en.auth.login.emailLabel), {
    target: { value: 'user@example.com' },
  })
  fireEvent.change(screen.getByLabelText(en.auth.login.passwordLabel), {
    target: { value: 'wrong' },
  })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: en.auth.login.submit }))
  })

  expect(window.sessionStorage.getItem(MARKER_KEY)).toBeNull()
})

// ── degrade, don't guess ─────────────────────────────────────────────────

it('falls back to the generic copy when storage is unavailable', () => {
  // A browser locked down enough to drop the session cookie may also refuse
  // storage. Refusing to render, or asserting the stronger message without
  // evidence, would both be worse than saying the plain true thing.
  // jsdom's Storage methods are not spy-able, so replace the whole object with
  // one that behaves like a browser refusing storage access.
  const real = Object.getOwnPropertyDescriptor(window, 'sessionStorage')
  const throwing = () => {
    throw new DOMException('The operation is insecure.', 'SecurityError')
  }
  Object.defineProperty(window, 'sessionStorage', {
    configurable: true,
    value: { getItem: throwing, setItem: throwing, removeItem: throwing },
  })
  mockSearchParams = new URLSearchParams('error=sign_in_required')

  try {
    expect(() => render(<LoginForm />)).not.toThrow()
    expect(message()).toBe(en.auth.errors.sign_in_required)
  } finally {
    if (real) Object.defineProperty(window, 'sessionStorage', real)
  }
})
