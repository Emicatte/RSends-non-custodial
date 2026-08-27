/**
 * "Repeat payment request" — the state-dependent row action on /app/payments.
 *
 * Two behaviours, one change:
 *   1. A link is only offered for copy while the intent can still be paid.
 *      Copying an expired or already-paid intent's link distributes a dead URL;
 *      those rows offer `Repeat` instead.
 *   2. `Repeat` opens the EXISTING creation modal prefilled from the source row.
 *      It never creates an intent by itself — the merchant confirms exactly as
 *      in manual creation — and it refuses to open at all when any value cannot
 *      be resolved into a valid current configuration.
 *
 * Expiry is DERIVED here: the session list serializes the stored status raw and
 * `expired` is only written by a 60s Celery task, so a past-expiry intent still
 * reads `pending` on the wire. `expires_at` is shipped precisely so the UI can
 * derive it, exactly as the public /pay route does in `_effective_status`.
 *
 * Same stack as paymentsPage.test.tsx: the real page + useOrgPayments +
 * useCurrentOrg + apiCall, with only fetch/next-auth/next-intl/navigation mocked.
 */
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

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

const WALLET = '0xabc0000000000000000000000000000000000001'
const A = '0x1111111111111111111111111111111111111111'
const B = '0x2222222222222222222222222222222222222222'
const C = '0x3333333333333333333333333333333333333333'

const FUTURE = '2099-01-01T00:00:00Z'
const PAST = '2020-01-01T00:00:00Z'

function orgPayload(role = 'admin') {
  return {
    organizations: [
      {
        id: 'o1',
        name: 'Org',
        slug: 'org',
        owner_user_id: 'u1',
        is_personal: false,
        plan: 'free',
        settlement_wallet: WALLET,
        role,
        member_count: 1,
        created_at: '2026-07-01T00:00:00Z',
      },
    ],
    active_org_id: 'o1',
  }
}

const CREATED = {
  intent_id: 'pi_new',
  recipient: A,
  amount: 100,
  currency: 'USDC',
  chain: 'base_sepolia',
  status: 'pending',
}

/** Route by URL (org lookup vs payments list) and by method (list vs create). */
function mockFetch(records: unknown[], role = 'admin') {
  const fn = jest.fn().mockImplementation((url: unknown, opts?: any) => {
    const u = String(url)
    if (u.includes('/organizations')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => orgPayload(role) })
    }
    if (opts?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: async () => CREATED })
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ total: records.length, page: 1, per_page: 20, records }),
    })
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

function row(overrides: Record<string, unknown> = {}) {
  return {
    intent_id: 'pi_src',
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'paid',
    recipient: A,
    tx_hash: null,
    matched_tx_hash: null,
    created_at: '2026-08-01T10:00:00Z',
    expires_at: PAST,
    ...overrides,
  }
}

/** The create POST body, or undefined when none was sent. */
function createBody(fn: jest.Mock): any {
  const call = fn.mock.calls.find(([, o]: any[]) => o?.method === 'POST')
  return call ? JSON.parse((call[1] as RequestInit).body as string) : undefined
}

afterEach(() => {
  jest.resetAllMocks()
})

it('offers Repeat, not Copy link, on an expired row', async () => {
  mockFetch([row({ status: 'expired' })])

  render(<AppPaymentsPage />)

  expect(await screen.findByRole('button', { name: 'Repeat' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy link' })).not.toBeInTheDocument()
})

it('keeps Copy link on a pending row that has not expired', async () => {
  mockFetch([row({ status: 'pending', expires_at: FUTURE })])

  render(<AppPaymentsPage />)

  expect(await screen.findByRole('button', { name: 'Copy link' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Repeat' })).not.toBeInTheDocument()
})

it('treats a pending row past its expiry as expired, because the list ships the stored status raw', async () => {
  mockFetch([row({ status: 'pending', expires_at: PAST })])

  render(<AppPaymentsPage />)

  // The wire still says "pending" — the 60s Celery task has not run. Offering
  // this link for copy would hand out a dead URL.
  expect(await screen.findByRole('button', { name: 'Repeat' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy link' })).not.toBeInTheDocument()
})

it('opens the creation modal prefilled with the source amount, token and recipient', async () => {
  mockFetch([row({ amount: 42.5 })])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))

  const dialog = await screen.findByRole('dialog')
  expect(screen.getByLabelText('Amount')).toHaveValue(42.5)
  expect(screen.getByLabelText('Token')).toHaveValue('USDC')
  expect(screen.getByLabelText('Recipient (optional)')).toHaveValue(A)
  // The create form is chain-locked; the source row's chain is the same one.
  // Scoped to the dialog — the row's own network cell reads the same string.
  expect(within(dialog).getByText('Base Sepolia')).toBeInTheDocument()
})

it('prefills every recipient and every share of a split source row', async () => {
  mockFetch([
    row({
      recipient: null,
      split: [
        { address: A, share_bps: 2500, position: 0 },
        { address: B, share_bps: 2500, position: 1 },
        { address: C, share_bps: 5000, position: 2 },
      ],
    }),
  ])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))
  await screen.findByRole('dialog')

  const addresses = screen.getAllByLabelText('Recipient (optional)')
  expect(addresses.map((i) => (i as HTMLInputElement).value)).toEqual([A, B, C])

  // Rows above the last are manual; the last balances to the remainder.
  const manual = screen.getAllByLabelText('Recipient amount')
  expect(manual.map((i) => (i as HTMLInputElement).value)).toEqual(['25', '25'])
  expect(screen.getByLabelText('Recipient amount (auto)')).toHaveValue('50')
})

it('refuses to open the modal when the token can no longer be offered, and fires no request', async () => {
  const fn = mockFetch([row({ currency: 'USDT' })])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(/token/i)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(createBody(fn)).toBeUndefined()
})

it('prefills the default expiry, never the source row expiry', async () => {
  mockFetch([row({ created_at: '2026-08-01T10:00:00Z', expires_at: PAST })])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))
  await screen.findByRole('dialog')

  // 30 minutes — the create default, not a value derived from the source.
  expect(screen.getByLabelText('Expires in')).toHaveValue('30')
})

it('creates from the prefilled values only when the merchant confirms, carrying no source intent id', async () => {
  const fn = mockFetch([row({ amount: 42.5 })])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))
  await screen.findByRole('dialog')

  // Opening the modal must not have created anything.
  expect(createBody(fn)).toBeUndefined()

  fireEvent.click(screen.getByRole('button', { name: 'Create payment request' }))

  await waitFor(() => expect(createBody(fn)).toBeDefined())
  const body = createBody(fn)
  expect(body).toEqual({
    amount: 42.5,
    currency: 'USDC',
    chain: 'base_sepolia',
    expires_in_minutes: 30,
    recipient: A,
  })
  expect(JSON.stringify(body)).not.toContain('pi_src')
})

it('reproduces a non-even split bit-identically on repeat', async () => {
  const stored = [
    { address: A, share_bps: 3333, position: 0 },
    { address: B, share_bps: 3333, position: 1 },
    { address: C, share_bps: 3334, position: 2 },
  ]
  const fn = mockFetch([row({ amount: 10, recipient: null, split: stored })])

  render(<AppPaymentsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Repeat' }))
  await screen.findByRole('dialog')
  fireEvent.click(screen.getByRole('button', { name: 'Create payment request' }))

  await waitFor(() => expect(createBody(fn)).toBeDefined())
  expect(createBody(fn).split).toEqual([
    { address: A, share_bps: 3333 },
    { address: B, share_bps: 3333 },
    { address: C, share_bps: 3334 },
  ])
})

it('offers a viewer no row action at all on a dead row', async () => {
  mockFetch([row({ status: 'expired' })], 'viewer')

  render(<AppPaymentsPage />)

  // The row renders (amount cell proves it) but carries neither action: a
  // viewer cannot create, and must not be handed a dead link either.
  expect(await screen.findByText('100 USDC')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Repeat' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy link' })).not.toBeInTheDocument()
})
