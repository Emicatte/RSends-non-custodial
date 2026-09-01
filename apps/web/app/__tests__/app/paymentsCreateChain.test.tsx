/**
 * The create-payment modal, chain-aware.
 *
 * Before this, Network was a static label reading "Base Sepolia" and the chain
 * was a module constant: a merchant could not create a TRON payment request
 * from the dashboard at all, only through the API. Everything asserted here is
 * a claim the form makes about what the SERVER will accept, so each test names
 * the server behaviour it is standing in for.
 *
 * The shared intl mock is used rather than this directory's older inline one
 * because the recipient errors take a `{network}` param; it throws on any
 * missing key, so rendering still doubles as an i18n guard.
 */
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

jest.mock('next-intl', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@/test-utils/intlMock').intlModuleMock(),
)

jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'

const EVM_WALLET = '0xabc0000000000000000000000000000000000001'
// Checksum-valid TRON addresses (base58check). The second is Tether's USDT
// contract on TRON — used only as a second well-formed T-address.
const TRON_WALLET = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const TRON_RECIPIENT = 'TJRabPrwbZy45sbavfcjinPJC18kjpRTv8'

const network = () => screen.getByLabelText('Network') as HTMLSelectElement
const tokenSelect = () => screen.getByLabelText('Token') as HTMLSelectElement
const submitBtn = () => screen.getByRole('button', { name: 'Create payment request' })

function tokenOptions(): string[] {
  return Array.from(tokenSelect().options).map((o) => o.value)
}

function selectTron() {
  fireEvent.change(network(), { target: { value: 'tron_nile' } })
}

function renderModal(props: Partial<React.ComponentProps<typeof CreatePaymentModal>> = {}) {
  return render(
    <CreatePaymentModal
      settlementWallet={EVM_WALLET}
      settlementWalletTron={TRON_WALLET}
      onCreate={jest.fn()}
      onClose={jest.fn()}
      {...props}
    />,
  )
}

afterEach(() => {
  jest.resetAllMocks()
})

// ── Token list follows the network ───────────────────────────────

it('offers only the tokens the registry enables on the selected network', () => {
  renderModal()

  // base_sepolia: ETH + USDC are enabled; USDT exists nowhere on it.
  expect(tokenOptions().sort()).toEqual(['ETH', 'USDC'])
  expect(tokenOptions()).not.toContain('USDT')

  selectTron()

  // tron_nile: USDT only. Offering USDC here would be a 400 UNSUPPORTED_TOKEN.
  expect(tokenOptions()).toEqual(['USDT'])
  expect(tokenOptions()).not.toContain('USDC')
  expect(tokenOptions()).not.toContain('ETH')
})

it('resets a token the new network does not enable', () => {
  renderModal()

  fireEvent.change(tokenSelect(), { target: { value: 'ETH' } })
  expect(tokenSelect().value).toBe('ETH')

  selectTron()
  // Not left on ETH, and not left blank — a valid token for the new chain.
  expect(tokenSelect().value).toBe('USDT')
  expect(tokenOptions()).toContain(tokenSelect().value)

  // And back again: USDT is not a base_sepolia token either.
  fireEvent.change(network(), { target: { value: 'base_sepolia' } })
  expect(tokenSelect().value).toBe('USDC')
})

// ── Split is impossible on TRON ──────────────────────────────────

it('hides split on TRON and clears half-filled split state on the way there', () => {
  renderModal()

  const toggle = screen.getByLabelText('Split payment')
  fireEvent.click(toggle)
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  // Half-fill it: a second payee address, no amounts.
  const addressFields = screen
    .getAllByRole('textbox')
    .filter((el) => (el as HTMLInputElement).placeholder === '0x…')
  fireEvent.change(addressFields[addressFields.length - 1], {
    target: { value: '0xdef0000000000000000000000000000000000002' },
  })

  selectTron()

  // Hidden, not disabled — there is no split router on TRON, ever.
  expect(screen.queryByLabelText('Split payment')).not.toBeInTheDocument()
  // The single-payee recipient field is what shows instead.
  expect(screen.getByLabelText('Recipient (optional)')).toBeInTheDocument()

  // Switching back must not restore the abandoned split: no toggle left on,
  // and no leg address surviving out of sight.
  fireEvent.change(network(), { target: { value: 'base_sepolia' } })
  expect(screen.getByLabelText('Split payment')).not.toBeChecked()
  expect(
    screen.queryByDisplayValue('0xdef0000000000000000000000000000000000002'),
  ).not.toBeInTheDocument()
})

// ── Recipient family gate ────────────────────────────────────────

it('rejects a 0x recipient on TRON, naming the network', () => {
  renderModal()
  selectTron()

  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  fireEvent.change(screen.getByLabelText('Recipient (optional)'), {
    target: { value: EVM_WALLET },
  })

  expect(
    screen.getByText('Enter a valid TRON address (T…) for TRON Nile.'),
  ).toBeInTheDocument()
  expect(submitBtn()).toBeDisabled()
})

it('rejects a T-address recipient on Base, naming the network', () => {
  renderModal()

  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  fireEvent.change(screen.getByLabelText('Recipient (optional)'), {
    target: { value: TRON_RECIPIENT },
  })

  expect(
    screen.getByText('Enter a valid 0x address for Base Sepolia.'),
  ).toBeInTheDocument()
  expect(submitBtn()).toBeDisabled()
})

it('uses the TRON placeholder on TRON and the 0x one on Base', () => {
  renderModal()
  expect(screen.getByLabelText('Recipient (optional)')).toHaveAttribute('placeholder', '0x…')
  selectTron()
  expect(screen.getByLabelText('Recipient (optional)')).toHaveAttribute('placeholder', 'T…')
})

// ── Where the money actually lands ───────────────────────────────

it('shows the payout address for the SELECTED chain, not always the EVM one', () => {
  renderModal()

  const settlesTo = () => screen.getByText('Payments settle to').parentElement!

  // Base: the EVM wallet, truncated.
  expect(within(settlesTo()).getByText('0xabc0…0001')).toBeInTheDocument()

  selectTron()

  // TRON: the TRON wallet. Showing the 0x address here would tell the merchant
  // the money lands somewhere it cannot.
  expect(within(settlesTo()).getByText('TR7NHq…Lj6t')).toBeInTheDocument()
  expect(within(settlesTo()).queryByText('0xabc0…0001')).not.toBeInTheDocument()
})

it('blocks submission and points at Settings when no TRON payout address is set', () => {
  // Server-side this is a 422 SETTLEMENT_WALLET_TRON_MISSING — reached only
  // after filling the whole form. Say it up front instead.
  renderModal({ settlementWalletTron: null })
  selectTron()

  expect(
    screen.getByText(
      'No TRON payout address is set. TRON payments cannot settle to your EVM settlement wallet.',
    ),
  ).toBeInTheDocument()
  // The TRON field lives on the organization tab, not the /settings root.
  expect(
    screen.getByRole('link', { name: 'Set TRON payout address' }),
  ).toHaveAttribute('href', '/settings/organization')

  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  expect(submitBtn()).toBeDisabled()

  // An explicit TRON recipient is the documented way through — the server
  // accepts the override regardless of the org default.
  fireEvent.change(screen.getByLabelText('Recipient (optional)'), {
    target: { value: TRON_RECIPIENT },
  })
  expect(submitBtn()).toBeEnabled()
})

it('still blocks on Base when the EVM wallet is missing, even with a TRON one set', () => {
  renderModal({ settlementWallet: null, settlementWalletTron: TRON_WALLET })

  expect(
    screen.getByText("Set your organization's settlement wallet to receive payments."),
  ).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  expect(submitBtn()).toBeDisabled()
})

// ── The request body ─────────────────────────────────────────────

it('submits a TRON intent with the TRON chain, token and recipient', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_tron',
    recipient: TRON_RECIPIENT,
    amount: 25,
    currency: 'USDT',
    chain: 'tron_nile',
    status: 'pending',
  })
  renderModal({ onCreate })

  selectTron()
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '25' } })
  fireEvent.change(screen.getByLabelText('Recipient (optional)'), {
    target: { value: TRON_RECIPIENT },
  })
  fireEvent.click(submitBtn())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 25,
      currency: 'USDT',
      chain: 'tron_nile',
      expires_in_minutes: 30,
      recipient: TRON_RECIPIENT,
    }),
  )
})

it('leaves the Base request body exactly as it was before the selector existed', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_base',
    recipient: null,
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  renderModal({ onCreate })

  // Touch nothing but the amount — the default path.
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  fireEvent.click(submitBtn())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 100,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
    }),
  )
})

it('keeps the Base body identical after a round trip through TRON', async () => {
  // The selector must not leave residue: switching away and back is the
  // cheapest way a stale token or a lingering split would show up in the body.
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_base',
    recipient: null,
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })
  renderModal({ onCreate })

  selectTron()
  fireEvent.change(network(), { target: { value: 'base_sepolia' } })
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  fireEvent.click(submitBtn())

  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 100,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
    }),
  )
})
