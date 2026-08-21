/**
 * Split payment creation from /app — CreatePaymentModal's split section and
 * useOrgPayments.createIntent's split payload.
 *
 * The merchant enters AMOUNTS per recipient, never percentages. Rows above
 * the LAST one are manual; the last row is the balance row — always
 * `total − sum(manual amounts)`, so the amounts sum to the Amount field by
 * construction. Contract bps are derived from the amount ratios
 * (sum EXACTLY 10000, ±1 bps absorbed on recipient 0) and the `≈` preview
 * appears ONLY when a typed amount is not a clean bps fraction of the
 * total, showing the true on-chain figure (floor + remainder to recipient
 * 0). Submit is blocked until every address is valid + unique and every
 * amount parses, fits the token's decimals, and leaves the balance row
 * positive. Each failure names itself. The POST carries integer share_bps
 * and never a `recipient` key; the server 422 remains authoritative.
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

// The org's own settlement wallet. The backend stores it LOWERCASE
// (org_schemas._validate_settlement_wallet), so the realistic casing mismatch
// is the merchant pasting the checksummed form out of a wallet UI.
const OWN = '0xabc0000000000000000000000000000000000001'
const OWN_CHECKSUMMED = '0xABC0000000000000000000000000000000000001'

const OWN_MARKER = 'Your settlement wallet'
const SELF_EXCLUDED =
  'None of these recipients is your settlement wallet. You will receive nothing from this payment.'

afterEach(() => {
  jest.resetAllMocks()
})

function openSplit() {
  fireEvent.click(screen.getByLabelText('Split payment'))
}

function setTotal(value: string) {
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value } })
}

function setAddress(index: number, address: string) {
  fireEvent.change(screen.getAllByPlaceholderText('0x…')[index], {
    target: { value: address },
  })
}

/** Type into a MANUAL amount input (rows above the balance row). */
function setAmount(index: number, value: string) {
  fireEvent.change(screen.getAllByLabelText('Recipient amount')[index], {
    target: { value },
  })
}

function balanceField() {
  return screen.getByLabelText('Recipient amount (auto)') as HTMLInputElement
}

function submitButton() {
  return screen.getByRole('button', { name: 'Create payment request' })
}

// ── Modal: amounts in, bps derived ───────────────────────────────

it('clean amounts: balance row fills to the total, no ≈, submit enabled', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()

  // Two rows: one manual amount input + the read-only balance row.
  expect(screen.getAllByLabelText('Recipient amount')).toHaveLength(1)
  expect(balanceField()).toHaveAttribute('readonly')

  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '6')

  expect(balanceField().value).toBe('24')
  expect(screen.queryByText(/≈/)).not.toBeInTheDocument()
  expect(screen.getByText('Total: 30 USDC')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

it('non-clean amounts stay valid and show the true on-chain figure with ≈', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '10') // 10/30 is not a clean bps fraction

  expect(balanceField().value).toBe('20')
  expect(screen.getByText('≈ 9.999 USDC')).toBeInTheDocument()
  expect(screen.getByText('≈ 20.001 USDC')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

it('a locale comma parses; clean fraction shows exact', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '7,5') // 7.5/30 = exactly 2500 bps

  expect(balanceField().value).toBe('22.5')
  expect(screen.queryByText(/≈/)).not.toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

it('changing the total re-derives the balance row from the current amount', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '6')
  expect(balanceField().value).toBe('24')

  setTotal('60')
  expect(balanceField().value).toBe('54')
  expect(screen.getByText('Total: 60 USDC')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

it('amounts over the total block with the exceed message', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '40')

  expect(submitButton()).toBeDisabled()
  expect(screen.getByText('Recipient amounts exceed the total.')).toBeInTheDocument()
})

it('more decimals than the token supports block with the amount message', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '0.0000001') // 7 decimals; USDC has 6

  expect(submitButton()).toBeDisabled()
  expect(
    screen.getByText('Enter a valid amount for every recipient.'),
  ).toBeInTheDocument()
})

it('duplicate addresses block submit and say so', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, ALICE)
  setAmount(0, '6')

  expect(submitButton()).toBeDisabled()
  expect(screen.getByText('Each address can only appear once.')).toBeInTheDocument()
})

it('submits derived bps summing to 10000 — clean and non-clean', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_split',
    recipient: null,
    amount: 30,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={onCreate} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '10')

  fireEvent.click(submitButton())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 30,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 3333 },
        { address: BOB, share_bps: 6667 },
      ],
    }),
  )
  await waitFor(() =>
    expect(screen.getByText('http://localhost/pay/pi_split')).toBeInTheDocument(),
  )
})

it('three rows: two manual amounts, the last balances in currency', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))

  expect(screen.getAllByLabelText('Recipient amount')).toHaveLength(2)
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAddress(2, CAROL)
  setAmount(0, '10')
  setAmount(1, '10')

  expect(balanceField().value).toBe('10')
  expect(submitButton()).toBeEnabled()
})

it('add and remove keep the last row as the balance row within 2..20', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  openSplit()
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))
  expect(screen.getAllByLabelText('Recipient amount')).toHaveLength(2)
  expect(screen.getAllByLabelText('Recipient amount (auto)')).toHaveLength(1)

  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[1])
  expect(screen.getAllByLabelText('Recipient amount')).toHaveLength(1)
  expect(screen.getAllByLabelText('Recipient amount (auto)')).toHaveLength(1)
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

// ── Self-exclusion: the split legs ARE the recipient set ─────────
//
// In single mode the recipient is implicit — the org settlement wallet,
// resolved server-side, never typed. A split sets `recipient` to NULL and the
// legs become the COMPLETE recipient set, so the settlement wallet receives
// nothing unless it is explicitly one of them. The router is immutable and
// non-custodial: once the payer signs there is no reversal. So row one is
// PREFILLED with the settlement wallet and marked as the merchant's own, and
// leaving it out is warned about at the point of confirmation — a warning,
// never a block: a pass-through platform taking nothing is legitimate.

function addressInputs() {
  return screen.getAllByPlaceholderText('0x…') as HTMLInputElement[]
}

it('prefills row one with the org settlement wallet, marked as the merchant own', () => {
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()

  const rows = addressInputs()
  expect(rows).toHaveLength(2)
  expect(rows[0].value).toBe(OWN)
  // Prefilling an address must not invent a share.
  expect(rows[1].value).toBe('')
  expect(screen.getAllByLabelText('Recipient amount')[0]).toHaveValue('')

  // An address alone is not recognisable — merchants do not read hex.
  expect(screen.getAllByText(OWN_MARKER)).toHaveLength(1)
})

it('the prefilled row is removable, and removing it does not re-add it', () => {
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()

  expect(addressInputs()[0].value).toBe(OWN)

  // Remove is disabled at the 2-leg floor, so the prefilled row is removable
  // under exactly the same rule as every other row — never special-cased.
  fireEvent.click(screen.getByRole('button', { name: 'Add recipient' }))
  expect(addressInputs()).toHaveLength(3)
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0])

  expect(addressInputs()).toHaveLength(2)
  expect(addressInputs().map((r) => r.value)).not.toContain(OWN)
  expect(screen.queryByText(OWN_MARKER)).not.toBeInTheDocument()

  // Any later re-render must not resurrect it.
  setTotal('40')
  expect(addressInputs().map((r) => r.value)).not.toContain(OWN)
  expect(screen.queryByText(OWN_MARKER)).not.toBeInTheDocument()
})

it('does not warn when the settlement wallet is among the legs', () => {
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(1, BOB)
  setAmount(0, '10')

  expect(submitButton()).toBeEnabled()
  expect(screen.queryByText(SELF_EXCLUDED)).not.toBeInTheDocument()
})

it('warns at confirmation when no leg is the settlement wallet', () => {
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE) // overwrite the prefill with a third party
  setAddress(1, BOB)
  setAmount(0, '10')

  expect(screen.getByRole('alert')).toHaveTextContent(SELF_EXCLUDED)
  expect(screen.queryByText(OWN_MARKER)).not.toBeInTheDocument()
})

it('matches the settlement wallet regardless of checksum casing', () => {
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  // As pasted out of a wallet UI: same address, different casing. A raw string
  // compare would accuse a merchant who DID include themselves.
  setAddress(0, OWN_CHECKSUMMED)
  setAddress(1, BOB)
  setAmount(0, '10')

  expect(screen.queryByText(SELF_EXCLUDED)).not.toBeInTheDocument()
  expect(screen.getAllByText(OWN_MARKER)).toHaveLength(1)
})

it('warns but never blocks — the split still submits', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_excluded',
    recipient: null,
    amount: 30,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={onCreate} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '10')

  expect(screen.getByRole('alert')).toHaveTextContent(SELF_EXCLUDED)
  expect(submitButton()).toBeEnabled()
  fireEvent.click(submitButton())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 30,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
      split: [
        { address: ALICE, share_bps: 3333 },
        { address: BOB, share_bps: 6667 },
      ],
    }),
  )
})

it('claims no exclusion while the settlement wallet is unknown', () => {
  // Absence of data is not evidence of exclusion.
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  setTotal('30')
  openSplit()
  setAddress(0, ALICE)
  setAddress(1, BOB)
  setAmount(0, '10')

  expect(submitButton()).toBeEnabled()
  expect(screen.queryByText(SELF_EXCLUDED)).not.toBeInTheDocument()
  expect(screen.queryByText(OWN_MARKER)).not.toBeInTheDocument()
})

it('drops the "settles to" claim in split mode but keeps the set-a-wallet prompt', () => {
  const { unmount } = render(
    <CreatePaymentModal settlementWallet={OWN} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  // Single mode says where the money lands; under a split that would be untrue.
  expect(screen.getByText(/Payments settle to/)).toBeInTheDocument()
  openSplit()
  expect(screen.queryByText(/Payments settle to/)).not.toBeInTheDocument()
  unmount()

  // A merchant who never set a wallet is the likeliest accidental
  // self-excluder — the prompt must survive the split toggle.
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )
  expect(screen.getByText(/Set your organization/)).toBeInTheDocument()
  openSplit()
  expect(screen.getByText(/Set your organization/)).toBeInTheDocument()
})
