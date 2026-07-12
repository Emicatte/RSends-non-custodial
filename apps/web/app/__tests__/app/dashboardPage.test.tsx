/**
 * The /app home page — checklist wiring seam.
 *
 * The component tests (dashboardChecklist.test.tsx) exercise GetStartedChecklist
 * with hand-built props; this file pins the PAGE-side mapping of the org-stats
 * booleans onto those props (settlement_wallet_set→wallet, has_api_key→apiKey,
 * has_paid_payment→testPayment) and the `loading && !stats` skeleton predicate,
 * through the real useOrgStats + apiCall stack with only fetch, next-auth,
 * next-intl and i18n navigation mocked (same scaffolding as paymentsPage).
 */
import { render, screen, waitFor } from '@testing-library/react'

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

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok' },
    status: 'authenticated',
  }),
}))

import AppDashboardPage from '@/app/[locale]/app/page'

function statsPayload(overrides: Record<string, unknown> = {}) {
  return {
    volume_24h: 1234,
    volume_24h_delta_pct: 0,
    transactions_24h: 0,
    transactions_24h_delta: 0,
    total_balance: 0,
    total_balance_chains: 0,
    active_clients: 0,
    active_clients_this_week: 0,
    recent_transactions: [],
    settlement_wallet_set: false,
    has_api_key: false,
    has_paid_payment: false,
    ...overrides,
  }
}

function mockFetch(body: unknown) {
  const fn = jest
    .fn()
    .mockResolvedValue({ ok: true, status: 200, json: async () => body })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

afterEach(() => {
  jest.resetAllMocks()
})

it('shows the checklist skeleton (no items, no title) while stats are loading', () => {
  // A fetch that never settles keeps the page in its loading state.
  global.fetch = jest.fn(
    () => new Promise(() => {}),
  ) as unknown as typeof fetch

  render(<AppDashboardPage />)

  expect(screen.getByTestId('get-started-skeleton')).toBeInTheDocument()
  expect(screen.queryByText('Get started')).not.toBeInTheDocument()
  expect(screen.queryAllByRole('link')).toHaveLength(0)
})

it('maps each stats boolean onto its checklist item', async () => {
  mockFetch(
    statsPayload({ settlement_wallet_set: true, has_paid_payment: true }),
  )

  render(<AppDashboardPage />)

  // apiKey is the only incomplete step → the only link on the page.
  const apiKey = await screen.findByRole('link', { name: /create an api key/i })
  expect(apiKey.getAttribute('href')).toContain('/app/api-keys')
  expect(screen.getAllByRole('link')).toHaveLength(1)

  // wallet + testPayment map to done: labels kept, not links, sr Completed.
  expect(screen.getByText(/add your settlement wallet/i)).toBeInTheDocument()
  expect(screen.getByText(/send a test payment/i)).toBeInTheDocument()
  expect(screen.getAllByText('Completed')).toHaveLength(2)
})

it('removes the card entirely when all three facts are complete', async () => {
  mockFetch(
    statsPayload({
      settlement_wallet_set: true,
      has_api_key: true,
      has_paid_payment: true,
    }),
  )

  render(<AppDashboardPage />)

  // Wait for the stats to land (volume metric renders) …
  await waitFor(() => expect(screen.getByText('$1,234')).toBeInTheDocument())

  // … then the card and its skeleton are both gone.
  expect(screen.queryByText('Get started')).not.toBeInTheDocument()
  expect(screen.queryByTestId('get-started-skeleton')).not.toBeInTheDocument()
  expect(screen.queryAllByRole('link')).toHaveLength(0)
})
