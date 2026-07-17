/**
 * Split payment creation from /app — CreatePaymentModal's split section and
 * useOrgPayments.createIntent's split payload.
 *
 * The client mirror of the server BPS gate: submit is BLOCKED until every
 * address is valid + unique and the shares sum to EXACTLY 100% (10000 bps) —
 * the server 422 remains authoritative. A valid split needs NO settlement
 * wallet (the split IS the recipient set). The POST carries integer
 * share_bps and never a `recipient` key.
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

afterEach(() => {
  jest.resetAllMocks()
})

function openSplit() {
  fireEvent.click(screen.getByLabelText('Split payment'))
}

function fillLeg(index: number, address: string, percent: string) {
  fireEvent.change(screen.getAllByPlaceholderText('0x…')[index], {
    target: { value: address },
  })
  fireEvent.change(screen.getAllByLabelText('Share %')[index], {
    target: { value: percent },
  })
}

// ── Modal: the client BPS gate ───────────────────────────────────

it('split toggle reveals two legs; submit blocked until shares sum to exactly 100%', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()

  // Two leg rows appear (min 2 recipients).
  expect(screen.getAllByLabelText('Share %')).toHaveLength(2)
  const submit = screen.getByRole('button', { name: 'Create payment request' })

  fillLeg(0, ALICE, '70')
  fillLeg(1, BOB, '20') // 90% — not exact
  expect(submit).toBeDisabled()

  fillLeg(1, BOB, '30') // exactly 100%
  expect(submit).toBeEnabled()

  fillLeg(1, BOB, '30.001') // sub-bps precision — rejected, never rounded
  expect(submit).toBeDisabled()
})

it('duplicate addresses block submit', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  openSplit()
  fillLeg(0, ALICE, '50')
  fillLeg(1, ALICE, '50')
  expect(
    screen.getByRole('button', { name: 'Create payment request' }),
  ).toBeDisabled()
})

it('submits integer bps with no recipient key — and needs no settlement wallet', async () => {
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
  fillLeg(0, ALICE, '70')
  fillLeg(1, BOB, '30')

  fireEvent.click(screen.getByRole('button', { name: 'Create payment request' }))

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 100,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 7000 },
        { address: BOB, share_bps: 3000 },
      ],
    }),
  )
  await waitFor(() =>
    expect(screen.getByText('http://localhost/pay/pi_split')).toBeInTheDocument(),
  )
})

it('can add and remove legs within 2..20', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))
  expect(screen.getAllByLabelText('Share %')).toHaveLength(3)
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[2])
  expect(screen.getAllByLabelText('Share %')).toHaveLength(2)
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
