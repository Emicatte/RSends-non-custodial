/**
 * Phase C/D — the /app payments list view.
 *
 * Exercises the real page + useOrgPayments + useCurrentOrg + apiCall stack with
 * only fetch, next-auth, next-intl and i18n navigation mocked. Proves:
 *   1. rows render from the session fetch (with the explorer link on paid rows),
 *   2. the empty state shows when there are none,
 *   3. the list request carries a Bearer token and NO wallet-signature headers,
 *      and never asks for the `live` environment (hard-locked to test).
 *
 * The next-intl mock throws on any missing key → also guards that the page
 * references no dangling app.payments.* i18n key (in en).
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

import AppPaymentsPage from '@/app/[locale]/app/payments/page'

const ORG_PAYLOAD = {
  organizations: [
    {
      id: 'o1',
      name: 'Org',
      slug: 'org',
      owner_user_id: 'u1',
      is_personal: false,
      plan: 'free',
      settlement_wallet: '0xabc0000000000000000000000000000000000001',
      role: 'admin',
      member_count: 1,
      created_at: '2026-07-01T00:00:00Z',
    },
  ],
  active_org_id: 'o1',
}

// Route by URL: the org lookup (useCurrentOrg) vs the payments list.
function mockFetch(paymentsPayload: unknown) {
  const fn = jest.fn().mockImplementation((url: unknown) => {
    const u = String(url)
    const body = u.includes('/organizations') ? ORG_PAYLOAD : paymentsPayload
    return Promise.resolve({ ok: true, status: 200, json: async () => body })
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

const PAID_ROW = {
  intent_id: 'pi_paid',
  amount: 100,
  currency: 'USDC',
  chain: 'base_sepolia',
  status: 'paid',
  recipient: '0xabcdef0000000000000000000000000000001234',
  tx_hash: null,
  matched_tx_hash: '0xhash1',
  created_at: '2026-07-08T10:00:00Z',
  expires_at: '2026-07-08T11:00:00Z',
}
const PENDING_ROW = {
  intent_id: 'pi_pending',
  amount: 50,
  currency: 'USDC',
  chain: 'base_sepolia',
  status: 'pending',
  recipient: null,
  tx_hash: null,
  matched_tx_hash: null,
  created_at: '2026-07-08T09:00:00Z',
  expires_at: '2026-07-08T10:00:00Z',
}

afterEach(() => {
  jest.resetAllMocks()
})

it('renders payment rows from the session fetch, with a BaseScan link on paid rows', async () => {
  mockFetch({ total: 2, page: 1, per_page: 20, records: [PAID_ROW, PENDING_ROW] })

  render(<AppPaymentsPage />)

  // Paid row → explorer link to Base Sepolia, built from chain + matched hash.
  const link = await screen.findByRole('link', { name: 'View' })
  expect(link).toHaveAttribute('href', 'https://sepolia.basescan.org/tx/0xhash1')

  // Truncated recipient (paid row) + header + 2 data rows proves both rendered.
  expect(screen.getByText('0xabcd…1234')).toBeInTheDocument()
  expect(screen.getAllByRole('row')).toHaveLength(3)
})

it('shows the empty state when there are no payments', async () => {
  mockFetch({ total: 0, page: 1, per_page: 20, records: [] })

  render(<AppPaymentsPage />)

  await waitFor(() =>
    expect(screen.getByText('No payments yet')).toBeInTheDocument(),
  )
})

it('lists with a Bearer token and NO wallet-signature headers, never asking for live', async () => {
  const fn = mockFetch({ total: 0, page: 1, per_page: 20, records: [] })

  render(<AppPaymentsPage />)

  await waitFor(() =>
    expect(
      fn.mock.calls.some(([u]: any[]) =>
        String(u).includes('/user/org/payment-intents'),
      ),
    ).toBe(true),
  )

  const call = fn.mock.calls.find(([u]: any[]) =>
    String(u).includes('/user/org/payment-intents'),
  ) as [string, RequestInit]
  const [url, options] = call
  // Hard-lock: the browser never requests the live environment.
  expect(String(url)).not.toContain('environment')

  const headers = new Headers(options.headers)
  expect(headers.get('authorization')).toBe('Bearer tok')
  for (const key of headers.keys()) {
    expect(key.toLowerCase().startsWith('x-wallet')).toBe(false)
  }
})
