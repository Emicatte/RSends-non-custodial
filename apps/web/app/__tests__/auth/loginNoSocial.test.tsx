/**
 * Social login is removed from the product: the login and signup forms must
 * render the email/password flow with NO Google/GitHub buttons and no
 * "or continue with" divider.
 */
import { render, screen } from '@testing-library/react'

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
    // SignupForm uses t.rich for the ToS line; the raw string is fine here.
    ;(t as any).rich = (key: string) => t(key)
    return t
  },
  useLocale: () => 'en',
}))

jest.mock('next-auth/react', () => ({
  signIn: jest.fn(),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

jest.mock('@/hooks/useEmailAuth', () => ({
  useEmailAuth: () => ({
    signup: jest.fn(),
    checkEmail: jest.fn(),
    resendVerification: jest.fn(),
    loading: false,
    error: null,
    clearError: jest.fn(),
  }),
}))

import { LoginForm } from '@/components/auth/LoginForm'
import { SignupForm } from '@/components/auth/SignupForm'

// eslint-disable-next-line @typescript-eslint/no-require-imports
const en = require('@/messages/en.json')

const SOCIAL_COPY = [
  /continue with google/i,
  /continue with github/i,
  /or continue with/i,
]

it('login renders the email/password flow with no social buttons', () => {
  render(<LoginForm />)

  expect(screen.getByText(en.auth.login.title)).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: en.auth.login.submit }),
  ).toBeInTheDocument()
  for (const copy of SOCIAL_COPY) {
    expect(screen.queryByText(copy)).not.toBeInTheDocument()
  }
})

it('signup renders the email flow with no social buttons', () => {
  render(<SignupForm />)

  expect(screen.getByText(en.auth.signup.title)).toBeInTheDocument()
  for (const copy of SOCIAL_COPY) {
    expect(screen.queryByText(copy)).not.toBeInTheDocument()
  }
})
