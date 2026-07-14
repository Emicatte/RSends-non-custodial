/**
 * Approval waiting screen — polls the onboarding state (15s base, backoff to
 * a 60s cap) and transitions ON ITS OWN when the operator decides: approved →
 * /app, declined → the decline page. No manual refresh anywhere.
 */
import { act, render, screen } from '@testing-library/react'

const mockReplace = jest.fn()
const mockRouter = { replace: mockReplace, refresh: jest.fn() }

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
  Link: ({ href, children, ...rest }: any) => (
    <a href={String(href)} {...rest}>
      {children}
    </a>
  ),
}))

let mockSession: { data: { access_token?: string } | null; status: string } = {
  data: { access_token: 'tok-1' },
  status: 'authenticated',
}
jest.mock('next-auth/react', () => ({
  useSession: () => mockSession,
}))

jest.mock('@/lib/onboarding-client', () => ({
  getOnboardingState: jest.fn(),
}))

import { getOnboardingState } from '@/lib/onboarding-client'
import {
  APPROVAL_POLL_BASE_MS,
  APPROVAL_POLL_MAX_MS,
  approvalTransition,
  nextPollDelay,
} from '@/lib/approvalPolling'
import { ApprovalPendingScreen } from '@/components/onboarding/ApprovalPendingScreen'

const stateMock = getOnboardingState as jest.Mock

const pendingState = {
  consents_current: true,
  age_attested: true,
  email_verified: false,
  active_org_id: 'org-1',
  onboarding_status: 'company_submitted',
  activation_status: 'not_started',
  approval_status: 'pending_approval',
  decline_reason: null,
  company_profile: { exists: true, submitted_at: '2026-07-13T00:00:00Z' },
}

beforeEach(() => {
  jest.useFakeTimers()
  mockReplace.mockClear()
  stateMock.mockReset()
  mockSession = { data: { access_token: 'tok-1' }, status: 'authenticated' }
})

afterEach(() => {
  jest.useRealTimers()
})

// ── Pure helpers ───────────────────────────────────────────────

describe('nextPollDelay', () => {
  it('backs off 15s → 30s → 60s and caps there', () => {
    expect(APPROVAL_POLL_BASE_MS).toBe(15_000)
    expect(APPROVAL_POLL_MAX_MS).toBe(60_000)
    expect(nextPollDelay(0)).toBe(15_000)
    expect(nextPollDelay(1)).toBe(30_000)
    expect(nextPollDelay(2)).toBe(60_000)
    expect(nextPollDelay(3)).toBe(60_000)
    expect(nextPollDelay(50)).toBe(60_000)
  })
})

describe('approvalTransition', () => {
  it('routes approved to the dashboard and declined to the decline page', () => {
    expect(approvalTransition('approved')).toBe('/app')
    expect(approvalTransition('declined')).toBe('/onboarding/declined')
    expect(approvalTransition('pending_approval')).toBeNull()
    expect(approvalTransition(null)).toBeNull()
  })
})

// ── The screen transitions without a reload ────────────────────

describe('ApprovalPendingScreen', () => {
  it('shows the waiting copy while pending', async () => {
    stateMock.mockResolvedValue(pendingState)

    render(<ApprovalPendingScreen />)
    await act(async () => {})

    expect(screen.getByText('Your account is being reviewed')).toBeInTheDocument()
    expect(mockReplace).not.toHaveBeenCalled()
  })

  it('transitions to /app on its own when the status flips to approved', async () => {
    stateMock
      .mockResolvedValueOnce(pendingState)
      .mockResolvedValue({ ...pendingState, approval_status: 'approved' })

    render(<ApprovalPendingScreen />)
    await act(async () => {})
    expect(mockReplace).not.toHaveBeenCalled()

    await act(async () => {
      jest.advanceTimersByTime(APPROVAL_POLL_BASE_MS)
    })

    expect(mockReplace).toHaveBeenCalledWith('/app')
  })

  it('routes to the decline page when declined', async () => {
    stateMock.mockResolvedValue({
      ...pendingState,
      approval_status: 'declined',
      decline_reason: 'prohibited category',
    })

    render(<ApprovalPendingScreen />)
    await act(async () => {})

    expect(mockReplace).toHaveBeenCalledWith('/onboarding/declined')
  })

  // ── Failure handling (pinned per incident 2026-07-14) ────────

  it('survives a transient poll failure and still transitions on approval', async () => {
    stateMock
      .mockRejectedValueOnce(new Error('refresh_unavailable'))
      .mockResolvedValue({ ...pendingState, approval_status: 'approved' })

    render(<ApprovalPendingScreen />)
    await act(async () => {})
    expect(mockReplace).not.toHaveBeenCalled()

    await act(async () => {
      jest.advanceTimersByTime(APPROVAL_POLL_BASE_MS)
    })

    expect(mockReplace).toHaveBeenCalledWith('/app')
  })

  it('session_expired STOPS the polling and shows a visible message with a login link', async () => {
    stateMock.mockRejectedValue(new Error('session_expired'))

    render(<ApprovalPendingScreen />)
    await act(async () => {})

    expect(screen.getByRole('alert')).toHaveTextContent('Your session expired')
    const link = screen.getByRole('link', { name: 'Log in again' })
    expect(link).toHaveAttribute('href', '/login?redirect=/onboarding/pending')

    // No infinite silent retry: no further polls after the terminal error.
    const callsAfterError = stateMock.mock.calls.length
    await act(async () => {
      jest.advanceTimersByTime(10 * APPROVAL_POLL_MAX_MS)
    })
    expect(stateMock.mock.calls.length).toBe(callsAfterError)
    expect(mockReplace).not.toHaveBeenCalled()
  })

  it('shows the expired message when the NextAuth session dies (no silent stall)', async () => {
    mockSession = { data: null, status: 'unauthenticated' }
    stateMock.mockResolvedValue(pendingState)

    render(<ApprovalPendingScreen />)
    await act(async () => {})

    expect(screen.getByRole('alert')).toHaveTextContent('Your session expired')
    expect(stateMock).not.toHaveBeenCalled()
  })

  it('surfaces a retrying notice after repeated transient failures, cleared on success', async () => {
    stateMock.mockRejectedValue(new Error('refresh_unavailable'))

    render(<ApprovalPendingScreen />)
    await act(async () => {}) // failure 1 (t=0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await act(async () => {
      jest.advanceTimersByTime(APPROVAL_POLL_BASE_MS) // failure 2
    })
    await act(async () => {
      jest.advanceTimersByTime(2 * APPROVAL_POLL_BASE_MS) // failure 3
    })
    await act(async () => {
      jest.advanceTimersByTime(APPROVAL_POLL_MAX_MS) // failure 4 → notice
    })
    expect(screen.getByRole('status')).toHaveTextContent('still retrying')

    // First success clears the notice and keeps waiting normally.
    stateMock.mockResolvedValue(pendingState)
    await act(async () => {
      jest.advanceTimersByTime(APPROVAL_POLL_MAX_MS)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(mockReplace).not.toHaveBeenCalled()
  })
})
