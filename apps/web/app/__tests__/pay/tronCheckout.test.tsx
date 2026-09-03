/**
 * TronCheckout — the watch-only instruction screen.
 *
 * Two values leave this page and get retyped or pasted somewhere else, and
 * both are unforgiving. The address is base58check, which is case-SENSITIVE
 * and excludes 0 O I l, so a folded T-address does not decode at all. The
 * amount is compared in exact base units with zero tolerance, and anything
 * short becomes a `partial` intent that is terminal and does not accumulate.
 *
 * So the assertions here are mostly about identity: what the page displays,
 * what it copies, and what it encodes into the QR are the same bytes as what
 * the API sent, with nothing in between having touched them.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())

import { TronCheckout } from '@/app/pay/[intentId]/_components/TronCheckout'
import { normalizeIntent, type RawPaymentIntent } from '@/lib/web3/paymentIntent'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'

// A real TRON mainnet address. The mixed case is the point of the fixture.
const TRON_PAYEE = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const TRON_HASH = 'cd'.repeat(32)
const EXPIRES = '2999-01-01T00:00:00Z'

function tronIntent(overrides: Partial<RawPaymentIntent> = {}) {
  return normalizeIntent(
    {
      status: 'pending',
      expires_at: EXPIRES,
      amount: 10.000001,
      amount_exact: '10.000001',
      currency: 'USDT',
      chain: 'TRON',
      recipient: TRON_PAYEE,
      merchant_name: 'Caffe Emi',
      onchain: null,
      ...overrides,
    } as RawPaymentIntent,
    'pi_' + '0'.repeat(32),
  )
}

function renderTron(overrides: Partial<RawPaymentIntent> = {}) {
  return render(
    <TronCheckout intent={tronIntent(overrides)} onLocalExpiry={() => {}} />,
  )
}

let writeText: jest.Mock

beforeEach(() => {
  writeText = jest.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
})

/**
 * The manual instructions, now collapsed beneath the wallet flow. Scoping the
 * amount queries to this block is what keeps them unambiguous: the CTA names
 * the amount too, and that is the point rather than an accident.
 */
function instructionBlock(): HTMLDetailsElement {
  const summary = screen.getByText('Pay from another wallet or exchange')
  const details = summary.closest('details')
  if (!details) throw new Error('the instruction block is not inside a <details>')
  return details as HTMLDetailsElement
}

/**
 * Terminal states must drop the WHOLE payment surface, wallet flow included —
 * not just the address. Today this holds because TronCheckout early-returns
 * the status views before the wallet block; this pins it. The wallet panel
 * mounts through next/dynamic, so a wrongly-rendered panel appears a beat
 * AFTER render — settle it before asserting absence, or the pin would pass
 * against a panel still loading. The empty async act() is that settle, and it
 * is deterministic, not timed: under jest a dynamic chunk resolves in
 * microtasks (the CJS transform makes import() a resolved-promise .then), and
 * act drains the whole microtask queue, chained promises included — verified
 * by the bite check in this test's history (a panel wrongly rendered in the
 * expired state IS caught through the dynamic mount). If next/dynamic ever
 * starts scheduling a real timer here, this pin goes vacuous rather than
 * flaky — re-verify the bite before trusting it after upgrading Next.
 */
async function expectNoWalletUi() {
  await act(async () => {})
  expect(
    screen.queryByRole('button', { name: /connect wallet/i }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: /pay .* USDT/i }),
  ).not.toBeInTheDocument()
}

describe('the instruction screen', () => {
  it('renders the wallet flow with the instruction block collapsed beneath it', async () => {
    renderTron()

    expect(screen.getByText(TRON_PAYEE)).toBeInTheDocument()
    expect(within(instructionBlock()).getByText(/10\.000001/)).toBeInTheDocument()
    expect(screen.getByText('Caffe Emi')).toBeInTheDocument()

    // A wallet CAN be connected here now, and that is the primary path: once
    // the page knows the payer's address it builds the exact transfer itself,
    // so nothing is retyped and no deeplink is guessed. Awaited because the
    // wallet stack is loaded client-only, to keep it out of the EVM bundle.
    expect(
      await screen.findByRole('button', { name: /connect wallet/i }),
    ).toBeInTheDocument()

    // The instructions are kept and collapsed, never removed: an exchange
    // cannot connect a wallet, and that is how a good share of these invoices
    // get paid. Closed by default, content still in the DOM.
    expect(instructionBlock().open).toBe(false)

    // The CTA names the amount, and those are the only two places it appears:
    // once to read, once to authorise.
    expect(
      screen.getByRole('button', { name: /pay 10\.000001 USDT/i }),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/10\.000001/)).toHaveLength(2)
  })

  it('warns that this is the TRC-20 network and no other', async () => {
    renderTron()
    const warning = screen.getByText(/TRC-20/)
    expect(warning).toHaveTextContent('USDT')
    expect(warning).toHaveTextContent('TRON')
    expect(warning).toHaveTextContent('ERC-20')
  })

  it('states that the amount must be exact', () => {
    renderTron()
    expect(screen.getByText(/partial payment/i)).toBeInTheDocument()
  })

  it('shows a countdown', () => {
    renderTron()
    expect(screen.getByText(/^\d+:\d{2}$/)).toBeInTheDocument()
  })
})

describe('the address survives the page byte-identical', () => {
  it('displays it with its case intact', () => {
    renderTron()
    const shown = screen.getByText(TRON_PAYEE)
    expect(shown.textContent).toBe(TRON_PAYEE)
    // If anything folded the address, these would start passing.
    expect(shown.textContent).not.toBe(TRON_PAYEE.toLowerCase())
    expect(shown.textContent).not.toBe(TRON_PAYEE.toUpperCase())
  })

  it('copies exactly what it displays', async () => {
    renderTron()
    await userEvent.click(screen.getByRole('button', { name: 'Copy the address' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(writeText).toHaveBeenCalledWith(TRON_PAYEE)
  })

  it('encodes the BARE address into the QR', () => {
    // Not a URI scheme. Exchange withdrawal screens scan for an address, and
    // the amount-embedding formats are not read uniformly across TRON wallets.
    renderTron()
    const qr = document.querySelector('[data-qr-value]')
    expect(qr).not.toBeNull()
    const encoded = qr!.getAttribute('data-qr-value')
    expect(encoded).toBe(TRON_PAYEE)
    expect(encoded).not.toMatch(/^tron:/i)
    expect(encoded).not.toContain('?')
    expect(encoded).not.toContain('amount')
  })
})

describe('the amount is the backend value, unmodified', () => {
  it('copies the exact decimal the matcher expects', async () => {
    renderTron()
    await userEvent.click(screen.getByRole('button', { name: 'Copy the amount' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    // Bare decimal: no currency, no grouping separator, nothing to strip
    // before pasting it into a wallet.
    expect(writeText).toHaveBeenCalledWith('10.000001')
  })

  it('renders amount_exact rather than re-deriving it from the float', () => {
    // The float would print "10.0"; amount_exact carries the token's scale.
    renderTron({ amount: 10, amount_exact: '10.000000' })
    expect(within(instructionBlock()).getByText(/10\.000000/)).toBeInTheDocument()
  })

  it('shows no instruction at all when the backend named no amount', () => {
    // Better an empty holding state than a number this page invented.
    renderTron({ amount_exact: null })
    expect(screen.queryByText(TRON_PAYEE)).not.toBeInTheDocument()
    expect(
      screen.getByText(/payment details are not available/i),
    ).toBeInTheDocument()
  })

  it('shows no instruction when the backend named no address', () => {
    renderTron({ recipient: null })
    expect(
      screen.getByText(/payment details are not available/i),
    ).toBeInTheDocument()
  })
})

describe('status', () => {
  it('shows what arrived and what is missing on a partial payment', async () => {
    renderTron({
      status: 'partial',
      amount_received: '4.5',
      underpaid_amount: '5.500001',
      matched_tx_hash: TRON_HASH,
    })

    const body = screen.getByText(/We received/)
    expect(body).toHaveTextContent('4.5')
    expect(body).toHaveTextContent('5.500001')
    expect(body).toHaveTextContent('USDT')

    // No top-up affordance: the matcher does not accumulate, so a second
    // transfer would not close this invoice either.
    expect(screen.queryByText(TRON_PAYEE)).not.toBeInTheDocument()
    expect(document.querySelector('[data-qr-value]')).toBeNull()
    await expectNoWalletUi()
    expect(screen.getByText(/Contact the merchant/i)).toBeInTheDocument()
  })

  it('links a partial payment to tronscan, never to basescan', () => {
    renderTron({
      status: 'partial',
      amount_received: '4.5',
      underpaid_amount: '5.500001',
      matched_tx_hash: TRON_HASH,
    })
    const link = screen.getByRole('link', { name: /View transaction/i })
    expect(link).toHaveAttribute(
      'href',
      `https://tronscan.org/#/transaction/${TRON_HASH}`,
    )
    expect(link.getAttribute('href')).not.toContain('basescan')
  })

  it('sends Nile to the Nile explorer', () => {
    renderTron({
      chain: 'tron_nile',
      status: 'paid',
      matched_tx_hash: TRON_HASH,
    })
    expect(
      screen.getByRole('link', { name: /View transaction/i }),
    ).toHaveAttribute(
      'href',
      `https://nile.tronscan.org/#/transaction/${TRON_HASH}`,
    )
  })

  it('shows the paid card once the transfer is matched', async () => {
    renderTron({ status: 'paid', matched_tx_hash: TRON_HASH })
    expect(screen.getByText(/already completed/i)).toBeInTheDocument()
    expect(screen.queryByText(TRON_PAYEE)).not.toBeInTheDocument()
    await expectNoWalletUi()
  })

  it('shows the expired card, with no address left on screen to pay', async () => {
    renderTron({ status: 'expired' })
    expect(screen.getByText(/has expired/i)).toBeInTheDocument()
    expect(screen.queryByText(TRON_PAYEE)).not.toBeInTheDocument()
    await expectNoWalletUi()
  })

  it('treats a cancelled intent the same way', async () => {
    renderTron({ status: 'cancelled' })
    expect(screen.queryByText(TRON_PAYEE)).not.toBeInTheDocument()
    await expectNoWalletUi()
  })
})

describe('the connected wallet flow', () => {
  // A payer address distinct from the payee, so "Paying from" can never match
  // the destination row by accident.
  const TRON_PAYER = 'TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb'

  /**
   * Minimal working adapter, in the shape tronWalletProvider.test.tsx uses:
   * live listeners (the provider subscribes to adapter events), a connect that
   * lands on a real address, and a network() that agrees with the intent's
   * chain so the connected branch renders without the wrong-network note.
   */
  function connectedAdapter(chainId: string) {
    const listeners = new Map<string, Set<(...args: never[]) => void>>()
    const adapter: Record<string, unknown> = {
      name: 'TronLink',
      address: null as string | null,
      readyState: 'Found',
      network: async () => ({ chainId }),
      connect: async () => {
        adapter.address = TRON_PAYER
      },
      disconnect: async () => {
        adapter.address = null
      },
      signTransaction: async (tx: unknown) => tx,
      on: (event: string, fn: (...args: never[]) => void) => {
        if (!listeners.has(event)) listeners.set(event, new Set())
        listeners.get(event)!.add(fn)
      },
      off: (event: string, fn: (...args: never[]) => void) =>
        listeners.get(event)?.delete(fn),
    }
    return adapter
  }

  it('reaches the connected branch through an injected adapter', async () => {
    const network = tronNetworkFor(tronIntent().raw.chain)
    if (!network) throw new Error('fixture chain resolved no TRON network')
    const adapter = connectedAdapter(network.chainId)

    render(
      <TronCheckout
        intent={tronIntent()}
        onLocalExpiry={() => {}}
        createAdapters={async () => ({
          tronlink: adapter as never,
          walletconnect: null,
        })}
      />,
    )

    const user = userEvent.setup()
    await user.click(
      await screen.findByRole('button', { name: /connect wallet/i }),
    )
    await user.click(await screen.findByRole('button', { name: /^TronLink$/ }))

    // Connected branch: the summary names the payer's own wallet and the pay
    // CTA is live — the whole point of connecting.
    expect(await screen.findByText('Paying from')).toBeInTheDocument()
    expect(screen.getByText(/TWd4Wr/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /pay 10\.000001 USDT/i }),
    ).toBeEnabled()
  })
})
