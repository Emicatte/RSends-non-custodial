/**
 * LoginForm failure branches — every failure must render localized copy
 * (2026-07-24 discovery: the prod silent-bounce loop landed on a pristine
 * login form; network errors rendered raw "Failed to fetch"; a signIn bridge
 * failure was misattributed to bad credentials).
 *
 * Contract:
 *  - ?error=session_expired (set by forced-logout bounces) renders the
 *    session-expired copy on mount; any other value is ignored (the param
 *    feeds a translation key, so it is whitelisted);
 *  - a fetch-level failure renders auth.errors.network_error, never the raw
 *    exception message;
 *  - a signIn failure AFTER a successful backend login renders
 *    auth.errors.auth_unavailable, NOT "Email or password is incorrect";
 *  - a backend 401 still renders invalid_credentials.
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

beforeEach(() => {
  jest.clearAllMocks()
  mockSearchParams = new URLSearchParams()
  global.fetch = fetchMock as unknown as typeof fetch
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

it('renders localized network copy when the login fetch itself fails', async () => {
  fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
  render(<LoginForm />)
  await submit()

  expect(screen.getByRole('alert')).toHaveTextContent(
    en.auth.errors.network_error,
  )
  expect(screen.queryByText(/failed to fetch/i)).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: en.auth.login.submit }),
  ).toBeEnabled()
})

it('renders auth_unavailable (not invalid_credentials) when signIn fails after a 200 login', async () => {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({
      access_token: 'tok',
      expires_in: 900,
      user_id: 'u1',
      email: 'user@example.com',
      email_verified: true,
    }),
  })
  mockSignIn.mockResolvedValue({ error: 'CredentialsSignin' })
  render(<LoginForm />)
  await submit()

  expect(screen.getByRole('alert')).toHaveTextContent(
    en.auth.errors.auth_unavailable,
  )
  expect(
    screen.queryByText(en.auth.errors.invalid_credentials),
  ).not.toBeInTheDocument()
  expect(mockPush).not.toHaveBeenCalled()
})

it('still renders invalid_credentials on a backend 401', async () => {
  fetchMock.mockResolvedValue({
    ok: false,
    status: 401,
    headers: { get: () => null },
    json: async () => ({ detail: { code: 'invalid_credentials', message: '' } }),
  })
  render(<LoginForm />)
  await submit()

  expect(screen.getByRole('alert')).toHaveTextContent(
    en.auth.errors.invalid_credentials,
  )
})

it('a successful login clears a seeded session-expired banner and navigates', async () => {
  mockSearchParams = new URLSearchParams('error=session_expired&redirect=/en/onboarding')
  fetchMock.mockResolvedValue({
    ok: true,
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
  expect(screen.getByRole('alert')).toBeInTheDocument()

  await submit()

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockPush).toHaveBeenCalledWith('/en/onboarding')
})
