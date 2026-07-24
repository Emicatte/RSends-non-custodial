/**
 * useOnboarding — an authenticated session whose access token never arrives
 * must resolve to the error state (gate page shows error + retry), not the
 * old no-state/no-error limbo that left "Checking your account status..."
 * on screen forever (2026-07-24 discovery, report §6.5).
 */
import { act, renderHook, waitFor } from '@testing-library/react'

let mockSessionState: { data: unknown; status: string } = {
  data: {},
  status: 'authenticated',
}

jest.mock('next-auth/react', () => ({
  useSession: () => mockSessionState,
  signOut: jest.fn(),
}))

jest.mock('@/lib/onboarding-client', () => ({
  getOnboardingState: jest.fn(),
}))

import { getOnboardingState } from '@/lib/onboarding-client'
import { useOnboarding } from '@/hooks/useOnboarding'

const stateMock = getOnboardingState as jest.Mock

beforeEach(() => {
  jest.useFakeTimers()
  jest.clearAllMocks()
})

afterEach(() => {
  jest.useRealTimers()
})

it('times out into the error state when authenticated but the token never lands', async () => {
  mockSessionState = { data: {}, status: 'authenticated' } // no access_token
  const { result } = renderHook(() => useOnboarding())

  // waitForToken polls up to 2s; nothing arrives.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(2_500)
  })

  expect(result.current.error).toBe(true)
  expect(result.current.loading).toBe(false)
  expect(result.current.state).toBeNull()
  expect(stateMock).not.toHaveBeenCalled()
})

it('proceeds normally when the token is present', async () => {
  mockSessionState = {
    data: { access_token: 'tok-1' },
    status: 'authenticated',
  }
  stateMock.mockResolvedValue({ approval_status: 'pending_approval' })
  const { result } = renderHook(() => useOnboarding())

  await act(async () => {
    await jest.advanceTimersByTimeAsync(0)
  })

  expect(stateMock).toHaveBeenCalledWith('tok-1')
  expect(result.current.error).toBe(false)
  expect(result.current.state).toEqual({ approval_status: 'pending_approval' })
})

it('recovers when the token arrives late via rsends:token-refreshed', async () => {
  mockSessionState = { data: {}, status: 'authenticated' }
  stateMock.mockResolvedValue({ approval_status: 'approved' })
  const { result } = renderHook(() => useOnboarding())

  await act(async () => {
    await jest.advanceTimersByTimeAsync(300)
    window.dispatchEvent(
      new CustomEvent('rsends:token-refreshed', {
        detail: { access_token: 'tok-late' },
      }),
    )
    await jest.advanceTimersByTimeAsync(300)
  })

  await waitFor(() => expect(stateMock).toHaveBeenCalledWith('tok-late'))
  expect(result.current.error).toBe(false)
})
