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
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok-1' },
    status: 'authenticated',
  }),
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
})
