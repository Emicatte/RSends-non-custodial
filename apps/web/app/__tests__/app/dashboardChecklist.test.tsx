/**
 * Dashboard additions: the persistent testnet banner and the "Get started"
 * checklist card. The card is DERIVED state (fed by the org-stats booleans):
 * while loading it must never show an item as incomplete (skeleton reserving
 * the final layout); completed items keep their label but render done —
 * muted, non-link, sr-only "Completed"; incomplete items stay links to the
 * existing surfaces; all-complete (or no data after load) renders nothing.
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

const LABELS = {
  wallet: /add your settlement wallet/i,
  apiKey: /create an api key/i,
  testPayment: /send a test payment/i,
} as const

const NONE = { wallet: false, apiKey: false, testPayment: false }

describe('GetStartedChecklist', () => {
  it('never shows an item as incomplete while loading (skeleton only)', () => {
    render(<GetStartedChecklist loading completed={null} />)

    expect(screen.getByTestId('get-started-skeleton')).toBeInTheDocument()
    expect(screen.queryAllByRole('link')).toHaveLength(0)
    expect(screen.queryByText('Get started')).not.toBeInTheDocument()
    for (const label of Object.values(LABELS)) {
      expect(screen.queryByText(label)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('Completed')).not.toBeInTheDocument()
  })

  it('renders nothing when there is no data after load (error state)', () => {
    const { container } = render(
      <GetStartedChecklist loading={false} completed={null} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('links the three items to existing surfaces when all are incomplete', () => {
    render(<GetStartedChecklist loading={false} completed={NONE} />)

    expect(screen.getByText('Get started')).toBeInTheDocument()

    const wallet = screen.getByRole('link', { name: LABELS.wallet })
    expect(wallet.getAttribute('href')).toContain('/settings')

    const apiKey = screen.getByRole('link', { name: LABELS.apiKey })
    expect(apiKey.getAttribute('href')).toContain('/app/api-keys')

    const payment = screen.getByRole('link', { name: LABELS.testPayment })
    expect(payment.getAttribute('href')).toContain('/app/payments')

    expect(screen.queryByText('Completed')).not.toBeInTheDocument()
  })

  it.each(['wallet', 'apiKey', 'testPayment'] as const)(
    'renders %s as done (label kept, not a link, sr Completed) when completed',
    (done) => {
      render(
        <GetStartedChecklist
          loading={false}
          completed={{ ...NONE, [done]: true }}
        />,
      )

      // The completed item keeps its label but is no longer actionable.
      expect(screen.getByText(LABELS[done])).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: LABELS[done] })).toBeNull()
      expect(screen.getAllByText('Completed')).toHaveLength(1)
      // "Completed" is for screen readers only — visually hidden inline style.
      expect(screen.getByText('Completed')).toHaveStyle({
        position: 'absolute',
        overflow: 'hidden',
      })

      // The other two stay links.
      for (const key of Object.keys(LABELS) as Array<keyof typeof LABELS>) {
        if (key === done) continue
        expect(screen.getByRole('link', { name: LABELS[key] })).toBeInTheDocument()
      }
    },
  )

  it('renders two done items and one remaining link', () => {
    render(
      <GetStartedChecklist
        loading={false}
        completed={{ wallet: true, apiKey: true, testPayment: false }}
      />,
    )

    expect(screen.getAllByText('Completed')).toHaveLength(2)
    expect(screen.getAllByRole('link')).toHaveLength(1)
    expect(
      screen.getByRole('link', { name: LABELS.testPayment }),
    ).toBeInTheDocument()
  })

  it('renders nothing at all when every step is complete', () => {
    const { container } = render(
      <GetStartedChecklist
        loading={false}
        completed={{ wallet: true, apiKey: true, testPayment: true }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})
