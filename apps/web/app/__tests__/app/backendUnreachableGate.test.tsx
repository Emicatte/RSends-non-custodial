/**
 * BackendUnreachableGate — the client-side retry gate the /app and /settings
 * layouts render when the server guard resolves 'unreachable'.
 *
 * Contract:
 *  - probe only once the session is authenticated (never a tokenless probe);
 *  - a probe that gets ANY HTTP response means the backend is reachable → hand
 *    back to the server guard via router.refresh() (the server guard is the
 *    authority on 4xx). Bounded so a persistently server-slow backend can't
 *    freeze the skeleton;
 *  - a definitive auth death (session_expired, or a 401 that survived the
 *    one-shot refresh) → replace('/login');
 *  - a network error / timeout / 5xx (no reachable answer) → backoff retry,
 *    then the error card;
 *  - classification is by HTTP STATUS (apiCall carries err.status), never by
 *    matching the per-route body code string.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'

const mockReplace = jest.fn()
const mockRefresh = jest.fn()
const mockRouter = { replace: mockReplace, refresh: mockRefresh }

let mockSessionState: { data: unknown; status: string } = {
  data: { access_token: 'tok-1' },
  status: 'authenticated',
}

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    return (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  useRouter: () => mockRouter,
}))

jest.mock('next-auth/react', () => ({
  useSession: () => mockSessionState,
}))

jest.mock('@/lib/onboarding-client', () => ({
  getOnboardingState: jest.fn(),
}))

import { getOnboardingState } from '@/lib/onboarding-client'
import {
  BackendUnreachableGate,
  RETRY_DELAYS_MS,
  RECHECK_MS,
  MAX_RECHECKS,
} from '@/components/app/BackendUnreachableGate'

const stateMock = getOnboardingState as jest.Mock

const HEADING = 'We could not reach the service'
const BODY = 'The connection timed out. This usually resolves in a few seconds.'
const RETRY = 'Try again'

/** An apiCall-style rejection carrying an HTTP status. */
function httpError(status: number, code = `code_${status}`) {
  return Object.assign(new Error(code), { status })
}

beforeEach(() => {
  jest.useFakeTimers()
  jest.clearAllMocks()
  mockSessionState = { data: { access_token: 'tok-1' }, status: 'authenticated' }
})

afterEach(() => {
  jest.useRealTimers()
})

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

async function exhaustOutageBudget() {
  await flush(0)
  for (const delay of RETRY_DELAYS_MS) await flush(delay)
}

it('does not probe while the session is still loading', async () => {
  mockSessionState = { data: null, status: 'loading' }
  stateMock.mockResolvedValue({ consents_current: true })
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(stateMock).not.toHaveBeenCalled()
  expect(mockReplace).not.toHaveBeenCalled()
  expect(screen.getByTestId('backend-unreachable-skeleton')).toBeInTheDocument()
})

it('starts probing once the session becomes authenticated', async () => {
  mockSessionState = { data: null, status: 'loading' }
  stateMock.mockRejectedValue(new TypeError('fetch failed'))
  const { rerender } = render(<BackendUnreachableGate />)
  await flush(0)
  expect(stateMock).not.toHaveBeenCalled()

  mockSessionState = { data: { access_token: 'tok-1' }, status: 'authenticated' }
  rerender(<BackendUnreachableGate />)
  await flush(0)
  expect(stateMock).toHaveBeenCalledTimes(1)
  expect(stateMock).toHaveBeenCalledWith('tok-1')
})

it('shows the pulsing skeleton and no error copy while retrying', async () => {
  stateMock.mockImplementation(() => new Promise(() => {}))
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(screen.getByTestId('backend-unreachable-skeleton')).toBeInTheDocument()
  expect(screen.queryByText(HEADING)).not.toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('retries a network outage following the backoff schedule, then stops', async () => {
  stateMock.mockRejectedValue(new TypeError('fetch failed'))
  render(<BackendUnreachableGate />)

  await flush(0)
  expect(stateMock).toHaveBeenCalledTimes(1)
  await flush(RETRY_DELAYS_MS[0])
  expect(stateMock).toHaveBeenCalledTimes(2)
  await flush(RETRY_DELAYS_MS[1])
  expect(stateMock).toHaveBeenCalledTimes(3)
  for (const delay of RETRY_DELAYS_MS.slice(2)) await flush(delay)
  expect(stateMock).toHaveBeenCalledTimes(RETRY_DELAYS_MS.length + 1)

  await flush(60_000)
  expect(stateMock).toHaveBeenCalledTimes(RETRY_DELAYS_MS.length + 1)
  expect(mockRefresh).not.toHaveBeenCalled()
})

it('treats a 5xx as an outage (retries, does not hand off)', async () => {
  stateMock.mockRejectedValue(httpError(503))
  render(<BackendUnreachableGate />)

  await flush(0)
  expect(mockRefresh).not.toHaveBeenCalled()
  await flush(RETRY_DELAYS_MS[0])
  expect(stateMock).toHaveBeenCalledTimes(2)
  expect(mockRefresh).not.toHaveBeenCalled()
})

it('renders the error card with the final copy after the outage budget', async () => {
  stateMock.mockRejectedValue(new TypeError('fetch failed'))
  render(<BackendUnreachableGate />)
  await exhaustOutageBudget()

  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByText(HEADING)).toBeInTheDocument()
  expect(screen.getByText(BODY)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: RETRY })).toBeInTheDocument()
  expect(
    screen.queryByTestId('backend-unreachable-skeleton'),
  ).not.toBeInTheDocument()
})

it('Try again restarts the retry budget', async () => {
  stateMock.mockRejectedValue(new TypeError('fetch failed'))
  render(<BackendUnreachableGate />)
  await exhaustOutageBudget()
  const before = stateMock.mock.calls.length

  fireEvent.click(screen.getByRole('button', { name: RETRY }))
  await flush(0)

  expect(screen.getByTestId('backend-unreachable-skeleton')).toBeInTheDocument()
  expect(stateMock).toHaveBeenCalledTimes(before + 1)
})

it('a reachable success hands back to the server guard via router.refresh()', async () => {
  stateMock
    .mockRejectedValueOnce(new TypeError('fetch failed'))
    .mockResolvedValue({ consents_current: true })
  render(<BackendUnreachableGate />)

  await flush(0)
  expect(mockRefresh).not.toHaveBeenCalled()
  await flush(RETRY_DELAYS_MS[0])
  expect(mockRefresh).toHaveBeenCalledTimes(1)
  expect(mockReplace).not.toHaveBeenCalled()
})

it('does not freeze if refresh keeps returning to the gate (bounded rechecks)', async () => {
  // Backend reachable to the client but the server guard keeps timing out:
  // refresh() never clears us. We must reach the error card, not hang.
  stateMock.mockResolvedValue({ consents_current: true })
  render(<BackendUnreachableGate />)

  await flush(0)
  for (let i = 0; i <= MAX_RECHECKS; i++) await flush(RECHECK_MS)

  expect(mockRefresh.mock.calls.length).toBeGreaterThanOrEqual(1)
  expect(screen.getByText(HEADING)).toBeInTheDocument()
})

it('a 403 (reachable but denied) hands off to the server guard, not login', async () => {
  stateMock.mockResolvedValueOnce(undefined) // unused; first call rejects below
  stateMock.mockReset()
  stateMock.mockRejectedValue(httpError(403, 'forbidden'))
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(mockReplace).not.toHaveBeenCalled()
  expect(mockRefresh).toHaveBeenCalledTimes(1)
})

it('session_expired replaces to login and stops retrying', async () => {
  stateMock.mockRejectedValue(new Error('session_expired'))
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(mockReplace).toHaveBeenCalledWith('/login')
  expect(mockRefresh).not.toHaveBeenCalled()
  await flush(120_000)
  expect(stateMock).toHaveBeenCalledTimes(1)
})

it('a 401 surviving the one-shot refresh replaces to login', async () => {
  stateMock.mockRejectedValue(httpError(401, 'invalid_token'))
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(mockReplace).toHaveBeenCalledWith('/login')
  await flush(120_000)
  expect(stateMock).toHaveBeenCalledTimes(1)
})

it('uses a refreshed token for subsequent attempts', async () => {
  stateMock.mockRejectedValue(new TypeError('fetch failed'))
  render(<BackendUnreachableGate />)
  await flush(0)
  expect(stateMock).toHaveBeenLastCalledWith('tok-1')

  act(() => {
    window.dispatchEvent(
      new CustomEvent('rsends:token-refreshed', {
        detail: { access_token: 'tok-2' },
      }),
    )
  })
  await flush(RETRY_DELAYS_MS[0])
  expect(stateMock).toHaveBeenLastCalledWith('tok-2')
})

it('unauthenticated session replaces to login without calling the API', async () => {
  mockSessionState = { data: null, status: 'unauthenticated' }
  render(<BackendUnreachableGate />)
  await flush(0)

  expect(mockReplace).toHaveBeenCalledWith('/login')
  expect(stateMock).not.toHaveBeenCalled()
})
