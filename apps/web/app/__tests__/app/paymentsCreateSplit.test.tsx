/**
 * Split payment creation from /app — CreatePaymentModal's split section and
 * useOrgPayments.createIntent's split payload.
 *
 * The client mirror of the server BPS gate, with the auto-remainder UX:
 * every row above the LAST one is manual; the last row is the balance row —
 * its share is always 10000 − sum(manual bps), never typed. Submit is
 * BLOCKED until every address is valid + unique, every manual share parses
 * to integer bps, and the balance row keeps at least 1 bps — which makes
 * the sum exactly 10000 by construction. Each failure names itself (bad
 * address / duplicate / bad share / over 100%) instead of blaming the sum.
 * Share inputs parse locale-safely (comma and dot). The POST carries
 * integer share_bps and never a `recipient` key; the server 422 remains
 * authoritative.
 */
import { render, screen, fireEvent, waitFor, renderHook, act } from '@testing-library/react'

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

import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'
import { useOrgPayments } from '@/hooks/useOrgPayments'
import AppPaymentsPage from '@/app/[locale]/app/payments/page'

const ALICE = '0x1111111111111111111111111111111111111111'
const BOB = '0x3333333333333333333333333333333333333333'
const CAROL = '0x5555555555555555555555555555555555555555'

afterEach(() => {
  jest.resetAllMocks()
})

function openSplit() {
  fireEvent.click(screen.getByLabelText('Split payment'))
}

function setAddress(index: number, address: string) {
  fireEvent.change(screen.getAllByPlaceholderText('0x…')[index], {
    target: { value: address },
  })
}

/** Type into a MANUAL share input (rows above the balance row). */
function setShare(index: number, percent: string) {
  fireEvent.change(screen.getAllByLabelText('Share %')[index], {
    target: { value: percent },
  })
}

function balanceField() {
  return screen.getByLabelText('Share % (auto)') as HTMLInputElement
}

function submitButton() {
  return screen.getByRole('button', { name: 'Create payment request' })
}

// ── Modal: the client BPS gate with the auto-balance row ─────────

it('last row auto-balances to the remainder; submit enables only then', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()

  // Two rows appear: one manual share input + the read-only balance row.
  expect(screen.getAllByLabelText('Share %')).toHaveLength(1)
  expect(balanceField()).toHaveAttribute('readonly')

  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '43.72')

  expect(balanceField().value).toBe('56.28')
  expect(submitButton()).toBeEnabled()

  // Sub-bps precision — rejected, never rounded; names the share error.
  setShare(0, '30.001')
  expect(submitButton()).toBeDisabled()
  expect(
    screen.getByText('Enter each share as a percent with up to two decimal places.'),
  ).toBeInTheDocument()
})

it('parses a locale comma in the share input', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '43,72')

  expect(balanceField().value).toBe('56.28')
  expect(submitButton()).toBeEnabled()
})

it('duplicate addresses block submit and say so — not the sum message', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, ALICE)
  setShare(0, '50')

  expect(submitButton()).toBeDisabled()
  expect(
    screen.getByText('Each address can only appear once.'),
  ).toBeInTheDocument()
  expect(
    screen.queryByText('Shares must total exactly 100%.'),
  ).not.toBeInTheDocument()
})

it('manual shares over 100% surface the overflow on the balance row and block', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))

  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAddress(2, CAROL)
  setShare(0, '70')
  setShare(1, '40') // 110% across the manual rows — nothing left to balance

  expect(submitButton()).toBeDisabled()
  expect(screen.getByText('Shares exceed 100%.')).toBeInTheDocument()
})

it('three rows: two manual shares, the last balances the rest', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))

  expect(screen.getAllByLabelText('Share %')).toHaveLength(2)
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAddress(2, CAROL)
  setShare(0, '43.72')
  setShare(1, '30')

  expect(balanceField().value).toBe('26.28')
  expect(submitButton()).toBeEnabled()
})

it('submits manual bps plus the derived remainder — no recipient key, no settlement wallet', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_split',
    recipient: null,
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={onCreate} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '43.72')

  fireEvent.click(submitButton())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 100,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 4372 },
        { address: BOB, share_bps: 5628 },
      ],
    }),
  )
  await waitFor(() =>
    expect(screen.getByText('http://localhost/pay/pi_split')).toBeInTheDocument(),
  )
})

// ── Per-row payout preview: derived from the CURRENT amount ──────

it('per-row payouts follow an amount change live; shares stay put', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '43.72')

  expect(screen.getByText('≈ 43.72 USDC')).toBeInTheDocument()
  expect(screen.getByText('≈ 56.28 USDC')).toBeInTheDocument()

  // The reported repro: change the amount AFTER first entry.
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '30' } })

  expect(screen.getByText('≈ 13.116 USDC')).toBeInTheDocument()
  expect(screen.getByText('≈ 16.884 USDC')).toBeInTheDocument()
  expect(screen.queryByText('≈ 43.72 USDC')).not.toBeInTheDocument()
  // Shares are amount-independent: bps inputs and the share total hold.
  expect((screen.getAllByLabelText('Share %')[0] as HTMLInputElement).value).toBe('43.72')
  expect(balanceField().value).toBe('56.28')
  expect(screen.getByText('Total: 100.00%')).toBeInTheDocument()
})

it('no payout preview without a valid amount', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '40')
  expect(screen.queryByText(/≈/)).not.toBeInTheDocument()
})

it('submitting after an amount change carries the current amount, bps unchanged', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_split_amt',
    recipient: null,
    amount: 30,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={onCreate} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setShare(0, '43.72')
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '30' } })

  fireEvent.click(submitButton())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 30,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 4372 },
        { address: BOB, share_bps: 5628 },
      ],
    }),
  )
})

it('add and remove keep the last row as the balance row within 2..20', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))
  // 3 rows = 2 manual + 1 balance.
  expect(screen.getAllByLabelText('Share %')).toHaveLength(2)
  expect(screen.getAllByLabelText('Share % (auto)')).toHaveLength(1)

  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[1])
  // Back to 1 manual + 1 balance.
  expect(screen.getAllByLabelText('Share %')).toHaveLength(1)
  expect(screen.getAllByLabelText('Share % (auto)')).toHaveLength(1)
})

// ── List: split rows render "Split · N" with a per-leg tooltip ───

it('payments list shows the split summary instead of a single recipient', async () => {
  const orgPayload = {
    organizations: [
      {
        id: 'o1', name: 'Org', slug: 'org', owner_user_id: 'u1',
        is_personal: false, plan: 'free',
        settlement_wallet: '0xabc0000000000000000000000000000000000001',
        role: 'admin', member_count: 1, created_at: '2026-07-01T00:00:00Z',
      },
    ],
    active_org_id: 'o1',
  }
  const paymentsPayload = {
    total: 1, page: 1, per_page: 20,
    records: [
      {
        intent_id: 'pi_split_row', amount: 100, currency: 'USDC',
        chain: 'base_sepolia', status: 'pending', recipient: null,
        split: [
          { address: ALICE, share_bps: 7000, position: 0 },
          { address: BOB, share_bps: 3000, position: 1 },
        ],
        tx_hash: null, matched_tx_hash: null,
        created_at: '2026-07-08T10:00:00Z', expires_at: '2026-07-08T11:00:00Z',
      },
    ],
  }
  const fn = jest.fn().mockImplementation((url: unknown) => {
    const body = String(url).includes('/organizations') ? orgPayload : paymentsPayload
    return Promise.resolve({ ok: true, status: 200, json: async () => body })
  })
  global.fetch = fn as unknown as typeof fetch

  render(<AppPaymentsPage />)

  await waitFor(() =>
    expect(
      // The tooltip title carries one leg per line; the default testing-library
      // normalizer collapses the newline to a space.
      screen.getByTitle('0x1111…1111 — 70% 0x3333…3333 — 30%'),
    ).toHaveTextContent('Split · 2'),
  )
})

// ── Hook: the POST carries the split untouched ───────────────────

it('createIntent POSTs the split legs verbatim and no recipient', async () => {
  const fn = jest.fn().mockImplementation((_url: unknown, opts: any) => {
    const body =
      opts?.method === 'POST'
        ? { intent_id: 'pi_s', recipient: null, amount: 10, currency: 'USDC', chain: 'base_sepolia', status: 'pending' }
        : { total: 0, page: 1, per_page: 20, records: [] }
    return Promise.resolve({ ok: true, status: 200, json: async () => body })
  })
  global.fetch = fn as unknown as typeof fetch

  const { result } = renderHook(() => useOrgPayments())

  await act(async () => {
    await result.current.createIntent({
      amount: 10,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 7000 },
        { address: BOB, share_bps: 3000 },
      ],
    })
  })

  const post = fn.mock.calls.find(([, o]: any[]) => o?.method === 'POST') as [
    string,
    RequestInit,
  ]
  expect(post).toBeDefined()
  const body = JSON.parse(String(post[1].body))
  expect(body.split).toEqual([
    { address: ALICE, share_bps: 7000 },
    { address: BOB, share_bps: 3000 },
  ])
  expect(body).not.toHaveProperty('recipient')
  expect(body).not.toHaveProperty('environment')
})
