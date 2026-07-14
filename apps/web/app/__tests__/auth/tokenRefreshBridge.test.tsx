/**
 * TokenRefreshBridge — persists reactively-refreshed access tokens into the
 * NextAuth JWT via useSession().update() (jwt callback trigger === 'update').
 * Without this, server-side guards read the login-time token forever and
 * bounce approved merchants to /onboarding.
 */
import { act, render } from '@testing-library/react'

const mockUpdate = jest.fn()
jest.mock('next-auth/react', () => ({
  useSession: () => ({ update: mockUpdate, data: null, status: 'authenticated' }),
}))

import { TokenRefreshBridge } from '@/components/auth/TokenRefreshBridge'

beforeEach(() => mockUpdate.mockClear())

describe('TokenRefreshBridge', () => {
  it('calls session update with the refreshed access token', () => {
    render(<TokenRefreshBridge />)

    act(() => {
      window.dispatchEvent(
        new CustomEvent('rsends:token-refreshed', { detail: { access_token: 'tok-9' } }),
      )
    })

    expect(mockUpdate).toHaveBeenCalledWith({ access_token: 'tok-9' })
  })

  it('ignores malformed events and unsubscribes on unmount', () => {
    const { unmount } = render(<TokenRefreshBridge />)

    act(() => {
      window.dispatchEvent(new CustomEvent('rsends:token-refreshed', { detail: {} }))
    })
    expect(mockUpdate).not.toHaveBeenCalled()

    unmount()
    act(() => {
      window.dispatchEvent(
        new CustomEvent('rsends:token-refreshed', { detail: { access_token: 'tok-9' } }),
      )
    })
    expect(mockUpdate).not.toHaveBeenCalled()
  })
})
