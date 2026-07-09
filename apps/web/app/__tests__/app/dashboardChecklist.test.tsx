/**
 * Dashboard additions: the persistent testnet banner and the "Get started"
 * checklist card. Proves the exact banner copy renders and the three
 * checklist items link to the existing surfaces only (settlement wallet in
 * settings, API keys tab, payments page).
 */
import { render, screen } from '@testing-library/react'

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
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

import { TestnetBanner } from '@/components/app/TestnetBanner'
import { GetStartedChecklist } from '@/components/app/GetStartedChecklist'

describe('TestnetBanner', () => {
  it('renders the exact testnet copy', () => {
    render(<TestnetBanner />)
    expect(
      screen.getByText(
        'Test environment. Payments run on Base Sepolia with test tokens. Mainnet access requires business verification.',
      ),
    ).toBeInTheDocument()
  })
})

describe('GetStartedChecklist', () => {
  it('links the three items to existing surfaces', () => {
    render(<GetStartedChecklist />)

    expect(screen.getByText('Get started')).toBeInTheDocument()

    const wallet = screen.getByRole('link', { name: /add your settlement wallet/i })
    expect(wallet.getAttribute('href')).toContain('/settings')

    const apiKey = screen.getByRole('link', { name: /create an api key/i })
    expect(apiKey.getAttribute('href')).toContain('/app/api-keys')

    const payment = screen.getByRole('link', { name: /send a test payment/i })
    expect(payment.getAttribute('href')).toContain('/app/payments')
  })
})
