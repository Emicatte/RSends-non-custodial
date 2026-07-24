/**
 * Onboarding gate — a dead session must redirect to /login, not hang on the
 * "Checking your account status..." copy forever (incident 2026-07-14: with
 * status unauthenticated, useOnboarding resolves loading=false/error=false/
 * state=null and the gate previously had no branch for it).
 */
import { act, render, screen } from '@testing-library/react'

const mockReplace = jest.fn()

jest.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

jest.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({ data: null, status: 'unauthenticated' }),
}))

jest.mock('@/hooks/useOnboarding', () => ({
  useOnboarding: () => ({
    state: null,
    loading: false,
    error: false,
    reload: jest.fn(),
  }),
}))

import OnboardingGatePage from '@/app/[locale]/onboarding/page'

describe('OnboardingGatePage with a dead session', () => {
  it('redirects to login instead of spinning forever', async () => {
    render(<OnboardingGatePage />)
    await act(async () => {})

    expect(mockReplace).toHaveBeenCalledWith(
      '/login?redirect=/onboarding&error=session_expired',
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
