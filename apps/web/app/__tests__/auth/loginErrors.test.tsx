/**
 * LoginForm failure taxonomy — every distinct failure must render its OWN
 * localized copy, and the "service unavailable" copy must be reachable ONLY
 * from a genuine upstream failure.
 *
 * Background (2026-08-26 incident): the login form told a user "Servizio di
 * autenticazione temporaneamente non disponibile" while the backend was
 * demonstrably healthy. The string was a catch-all for "signIn() failed after
 * a 200 login" — a session-bridge failure, not an outage. Saying the service
 * is down when it is not is the specific false statement being fixed here.
 *
 * Contract:
 *  - ?error=session_expired (set by forced-logout bounces) renders the
 *    session-expired copy on mount; any other value is ignored (the param
 *    feeds a translation key, so it is whitelisted);
 *  - fetch rejected            -> network_error       (never raw "Failed to fetch")
 *  - abort / timeout           -> request_timeout     (NOT service-unavailable)
 *  - upstream 5xx              -> auth_unavailable    (the ONLY legitimate producer)
 *  - 200 with a non-JSON body  -> auth_unavailable    (server answered garbage)
 *  - 401                       -> invalid_credentials, byte-identical for an
 *                                 unknown email and a wrong password (enumeration)
 *  - 429                       -> rate_limit_exceeded
 *  - signIn fails after 200    -> session_bridge_failed (credentials WERE accepted)
 *  - every failure emits a correlation id, logged and shown, joinable to the
 *    backend's X-Request-ID / X-Correlation-ID;
 *  - no auth call is ever retried automatically (rate-limit / lockout hazard).
 */
import { act, fireEvent, render, screen } from '@testing-library/react'

const mockPush = jest.fn()
const mockSignIn = jest.fn()
let mockSearchParams = new URLSearchParams()

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

const fetchMock = jest.fn()
let errorSpy: jest.SpyInstance

/** RFC-4122 shape — the backend regenerates X-Request-ID unless it parses as a UUID. */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

beforeEach(() => {
  jest.clearAllMocks()
  mockSearchParams = new URLSearchParams()
  global.fetch = fetchMock as unknown as typeof fetch
  errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  errorSpy.mockRestore()
})

async function submit() {
  fireEvent.change(screen.getByLabelText(en.auth.login.emailLabel), {
    target: { value: 'user@example.com' },
  })
  fireEvent.change(screen.getByLabelText(en.auth.login.passwordLabel), {
    target: { value: 'hunter2hunter2' },
  })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: en.auth.login.submit }))
  })
}

/** The rendered message alone, without the correlation-id reference line. */
function message(): string {
  return screen.getByTestId('auth-error-message').textContent ?? ''
}

function okLoginResponse() {
  return {
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
  }
}

function errorResponse(status: number, code?: string) {
  return {
    ok: false,
    status,
    headers: { get: () => null },
    json: async () =>
      code ? { detail: { code, message: '' } } : { error: 'BACKEND_UNREACHABLE' },
  }
}

// ── pre-existing contract (unchanged) ────────────────────────────────────

it('renders the session-expired copy when bounced with ?error=session_expired', () => {
  mockSearchParams = new URLSearchParams('error=session_expired')
  render(<LoginForm />)

  expect(screen.getByRole('alert')).toHaveTextContent(
    en.auth.errors.session_expired,
  )
})

it('ignores a non-whitelisted ?error value', () => {
  mockSearchParams = new URLSearchParams('error=approval_pending')
  render(<LoginForm />)

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('a successful login clears a seeded session-expired banner and navigates', async () => {
  mockSearchParams = new URLSearchParams(
    'error=session_expired&redirect=/en/onboarding',
  )
  fetchMock.mockResolvedValue(okLoginResponse())
  mockSignIn.mockResolvedValue({ ok: true, error: undefined })
  render(<LoginForm />)
  expect(screen.getByRole('alert')).toBeInTheDocument()

  await submit()

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockPush).toHaveBeenCalledWith('/en/onboarding')
})

// ── (a) request never left the client ────────────────────────────────────

it('renders localized network copy when the login fetch itself fails', async () => {
  fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.network_error)
  expect(screen.queryByText(/failed to fetch/i)).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: en.auth.login.submit }),
  ).toBeEnabled()
})

// ── (b) client-side timeout ──────────────────────────────────────────────

it('renders the timeout copy — NOT service-unavailable — when the request aborts', async () => {
  fetchMock.mockRejectedValue(
    new DOMException('signal timed out', 'TimeoutError'),
  )
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.request_timeout)
  expect(message()).not.toBe(en.auth.errors.auth_unavailable)
})

it('bounds the login request with an abort signal', async () => {
  fetchMock.mockResolvedValue(okLoginResponse())
  mockSignIn.mockResolvedValue({ ok: true, error: undefined })
  render(<LoginForm />)
  await submit()

  const init = fetchMock.mock.calls[0][1]
  expect(init.signal).toBeDefined()
})

// ── (c) genuine upstream failure — the ONLY producer of auth_unavailable ──

it('renders service-unavailable on an upstream 502', async () => {
  fetchMock.mockResolvedValue(errorResponse(502))
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.auth_unavailable)
})

it('renders service-unavailable when a 200 carries a non-JSON body', async () => {
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => {
      throw new SyntaxError('Unexpected token < in JSON at position 0')
    },
  })
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.auth_unavailable)
  expect(mockSignIn).not.toHaveBeenCalled()
})

// ── (d) invalid credentials — must not leak whether the email exists ──────

it('renders byte-identical copy for an unknown email and a wrong password', async () => {
  fetchMock.mockResolvedValue(errorResponse(401, 'invalid_credentials'))
  const first = render(<LoginForm />)
  await submit()
  const unknownEmail = message()
  first.unmount()

  fetchMock.mockResolvedValue(errorResponse(401, 'invalid_credentials'))
  render(<LoginForm />)
  await submit()
  const wrongPassword = message()

  expect(unknownEmail).toBe(en.auth.errors.invalid_credentials)
  expect(wrongPassword).toBe(unknownEmail)
})

it('collapses any 401 body code to the generic invalid-credentials copy', async () => {
  // Defense in depth: even if a backend variant ever leaked a distinguishing
  // code at 401, the payer-visible string must not change.
  fetchMock.mockResolvedValue(errorResponse(401, 'user_not_found'))
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.invalid_credentials)
})

// ── (e) rate limited ─────────────────────────────────────────────────────

it('renders the rate-limited copy on a 429', async () => {
  fetchMock.mockResolvedValue(errorResponse(429, 'rate_limit_exceeded'))
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.rate_limit_exceeded)
})

// ── (f) session-bridge failure — the actual 2026-08-26 incident ───────────

it('renders session_bridge_failed — not service-unavailable — when signIn fails after a 200 login', async () => {
  fetchMock.mockResolvedValue(okLoginResponse())
  mockSignIn.mockResolvedValue({ error: 'CredentialsSignin' })
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.session_bridge_failed)
  expect(message()).not.toBe(en.auth.errors.auth_unavailable)
  expect(message()).not.toBe(en.auth.errors.invalid_credentials)
  expect(mockPush).not.toHaveBeenCalled()
})

it('renders session_bridge_failed when signIn resolves undefined', async () => {
  fetchMock.mockResolvedValue(okLoginResponse())
  mockSignIn.mockResolvedValue(undefined)
  render(<LoginForm />)
  await submit()

  expect(message()).toBe(en.auth.errors.session_bridge_failed)
})

// ── correlation id on every failure path ─────────────────────────────────

const failures: Array<[string, () => void]> = [
  ['network', () => fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))],
  [
    'timeout',
    () =>
      fetchMock.mockRejectedValue(
        new DOMException('signal timed out', 'TimeoutError'),
      ),
  ],
  ['upstream 5xx', () => fetchMock.mockResolvedValue(errorResponse(502))],
  ['401', () => fetchMock.mockResolvedValue(errorResponse(401, 'invalid_credentials'))],
  ['429', () => fetchMock.mockResolvedValue(errorResponse(429, 'rate_limit_exceeded'))],
  [
    'session bridge',
    () => {
      fetchMock.mockResolvedValue(okLoginResponse())
      mockSignIn.mockResolvedValue({ error: 'CredentialsSignin' })
    },
  ],
]

it.each(failures)('emits a correlation id on a %s failure', async (_label, arrange) => {
  arrange()
  render(<LoginForm />)
  await submit()

  const shown = screen.getByTestId('auth-error-reference').textContent ?? ''
  const id = shown.trim().split(/\s+/).pop() ?? ''
  expect(id).toMatch(UUID_RE)

  expect(errorSpy).toHaveBeenCalled()
  const logged = errorSpy.mock.calls.at(-1)?.[1] as Record<string, unknown>
  expect(logged).toMatchObject({ correlationId: id })
  expect(typeof logged.code).toBe('string')
})

it('sends the correlation id upstream so it can be joined to a backend request id', async () => {
  fetchMock.mockResolvedValue(errorResponse(502))
  render(<LoginForm />)
  await submit()

  const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
  const shown = screen.getByTestId('auth-error-reference').textContent ?? ''
  const id = shown.trim().split(/\s+/).pop() ?? ''

  expect(headers['X-Request-ID']).toBe(id)
  expect(headers['X-Correlation-ID']).toBe(id)
})

// ── no automatic retries on an auth endpoint ─────────────────────────────

it('never retries the login call automatically', async () => {
  fetchMock.mockResolvedValue(errorResponse(502))
  render(<LoginForm />)
  await submit()

  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(mockSignIn).not.toHaveBeenCalled()
})

it('never retries after a network failure', async () => {
  fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
  render(<LoginForm />)
  await submit()

  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('does not re-run the bridge when signIn fails', async () => {
  fetchMock.mockResolvedValue(okLoginResponse())
  mockSignIn.mockResolvedValue({ error: 'CredentialsSignin' })
  render(<LoginForm />)
  await submit()

  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(mockSignIn).toHaveBeenCalledTimes(1)
})
