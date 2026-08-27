/**
 * Hosted-checkout presentational components: per-state copy (the throwing
 * intl mock doubles as a missing-key guard), DM Mono on every numeric or
 * technical value, explorer hrefs from the central chain config, >=44px
 * touch targets, tx hash visible from the moment it exists, and terminal
 * views without any wallet UI.
 */
import { render, screen } from '@testing-library/react'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())

import {
  GasNote,
  PayerAddress,
  TotalHeadline,
} from '@/app/pay/[intentId]/_components/SummarySection'
import { TrustFooter } from '@/app/pay/[intentId]/_components/TrustFooter'
import { ActionArea } from '@/app/pay/[intentId]/_components/ActionArea'
import { CheckoutFrame } from '@/app/pay/[intentId]/_components/CheckoutFrame'
import {
  AlreadyPaidView,
  ExpiredView,
  NotFoundView,
  SuccessView,
} from '@/app/pay/[intentId]/_components/StatusViews'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'

const ROUTER = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA' as const
const HASH = '0x' + 'ab'.repeat(32)

const ONCHAIN: OnChainIntent = {
  invoiceId: ('0x' + 'cd'.repeat(32)) as `0x${string}`,
  merchant: ROUTER,
  token: '0x036CbD53842c5426634e7929541eC2318f3dCF7e',
  amount: 50_000_000n,
  fee: 600_000n,
  decimals: 6,
  chainId: 84532,
  router: ROUTER,
  routerVersion: 1,
  permitType: 'eip2612',
  permitVersion: '2',
}

const MONO = 'var(--font-mono)'

function actionProps(step: string, overrides: Record<string, unknown> = {}) {
  return {
    step: step as never,
    onchain: ONCHAIN,
    currency: 'USDC',
    total: 50_600_000n,
    networkLabel: 'Base Sepolia',
    connectSlot: <div data-testid="connect-slot" />,
    approveHash: null,
    payHash: null,
    waitingLong: false,
    canSwitchWallet: true,
    onSwitch: jest.fn(),
    onApprove: jest.fn(),
    onPay: jest.fn(),
    onRetry: jest.fn(),
    onUseOtherWallet: jest.fn(),
    ...overrides,
  }
}

describe('TotalHeadline', () => {
  it('renders the single total in DM Mono with token decimals and no breakdown', () => {
    render(
      <TotalHeadline total={50_600_000n} currency="USDC" decimals={ONCHAIN.decimals} />,
    )
    const node = screen.getByText('50.6')
    expect(node.closest('span')).toHaveStyle({ fontFamily: MONO })
    expect(screen.getByText('USDC')).toBeInTheDocument()
    // The breakdown is gone: no fee/total labels, no principal figure.
    expect(screen.queryByText('RSends fee')).toBeNull()
    expect(screen.queryByText('Total')).toBeNull()
    expect(screen.queryByText('Amount')).toBeNull()
  })

  it('holds a placeholder while the total is quoting and never shows the bare principal', () => {
    render(<TotalHeadline total={null} currency="USDC" decimals={ONCHAIN.decimals} />)
    expect(screen.getByTestId('amount-pending')).toBeInTheDocument()
    expect(screen.queryByText('50')).toBeNull()
    expect(screen.queryByText('50 USDC')).toBeNull()
    // The currency ticker stays visible next to the placeholder.
    expect(screen.getByText('USDC')).toBeInTheDocument()
  })
})

describe('GasNote', () => {
  it('renders the wallet-gas note', () => {
    render(<GasNote />)
    expect(
      screen.getByText('Your wallet adds a small network gas fee on top.'),
    ).toBeInTheDocument()
  })
})

// ── Which account is about to pay ────────────────────────────────
//
// A payer about to send an irreversible transfer must be able to see which
// address is sending it. Before this the ConnectButton was unmounted the
// moment the payer connected, and the card showed an amount and nothing else.

describe('CheckoutFrame wallet slot', () => {
  const slots = {
    header: <div />, amount: <div />, summary: <div />,
    action: <div />, notice: null, footer: <div />,
  }

  it('reserves the wallet line whether or not it is filled (zero CLS)', () => {
    // Connecting a wallet must not push the amount down the card. The frame
    // reserves every slot for exactly this reason; the skeleton renders the
    // same frame, so loading -> live -> connected never shifts.
    const { rerender } = render(<CheckoutFrame {...slots} />)
    const empty = screen.getByTestId('frame-wallet')
    expect(empty).toBeEmptyDOMElement()
    expect(empty).toHaveStyle({ minHeight: '34px' })

    rerender(<CheckoutFrame {...slots} wallet={<span>0x1111…1111</span>} />)
    expect(screen.getByTestId('frame-wallet')).toHaveStyle({ minHeight: '34px' })
  })
})

describe('PayerAddress', () => {
  const PAYER = '0x1111111111111111111111111111111111111111'

  it('renders the truncated address in DM Mono, no click target', () => {
    render(<PayerAddress address={PAYER} label="Paying from" />)
    expect(screen.getByText('Paying from')).toBeInTheDocument()
    const value = screen.getByText('0x1111…1111')
    expect(value).toHaveStyle({ fontFamily: MONO })
    // Read-only by construction: nothing here can drop a wallet mid-payment.
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('renders nothing without an address', () => {
    const { container } = render(<PayerAddress address={null} label="Paying from" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('TrustFooter', () => {
  it('renders exactly the two trust lines and links the router on the explorer', () => {
    render(<TrustFooter chainId={84532} router={ROUTER} />)
    expect(
      screen.getByText(
        "Funds go directly to the merchant's wallet. RSends never holds your money.",
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Executed by an immutable smart contract.'),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'View contract' })
    expect(link).toHaveAttribute(
      'href',
      `https://sepolia.basescan.org/address/${ROUTER}`,
    )
  })
})

describe('ActionArea per step', () => {
  it('connect renders the connect slot', () => {
    render(<ActionArea {...actionProps('connect')} />)
    expect(screen.getByTestId('connect-slot')).toBeInTheDocument()
  })

  it('wrong_network shows the copy and a switch button', () => {
    const props = actionProps('wrong_network')
    render(<ActionArea {...props} />)
    expect(
      screen.getByText('This payment runs on Base Sepolia. Switch your wallet to continue.'),
    ).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Switch network' })
    button.click()
    expect(props.onSwitch).toHaveBeenCalled()
  })

  it('insufficient_balance names the token and the required total', () => {
    render(<ActionArea {...actionProps('insufficient_balance')} />)
    expect(
      screen.getByText(
        'Not enough USDC in this wallet. You need 50.6 USDC plus gas.',
      ),
    ).toBeInTheDocument()
  })

  it('needs_approve shows the two-step indicator, explainer and approve button', () => {
    const props = actionProps('needs_approve')
    render(<ActionArea {...props} />)
    expect(screen.getByText('Step 1 of 2: Approve USDC')).toBeInTheDocument()
    expect(
      screen.getByText(
        'First allow the contract to use your USDC, then confirm the payment. Two wallet confirmations in total.',
      ),
    ).toBeInTheDocument()
    screen.getByRole('button', { name: 'Approve USDC' }).click()
    expect(props.onApprove).toHaveBeenCalled()
  })

  it('ready_to_pay shows step 2 and the pay button with the total', () => {
    const props = actionProps('ready_to_pay')
    render(<ActionArea {...props} />)
    expect(screen.getByText('Step 2 of 2: Confirm payment')).toBeInTheDocument()
    screen.getByRole('button', { name: 'Pay 50.6 USDC' }).click()
    expect(props.onPay).toHaveBeenCalled()
  })

  it('ready (permit path) shows the pay button with NO step indicator', () => {
    render(<ActionArea {...actionProps('ready')} />)
    expect(screen.getByRole('button', { name: 'Pay 50.6 USDC' })).toBeInTheDocument()
    expect(screen.queryByText(/Step \d of 2/)).toBeNull()
  })

  it('approving/paying show the waiting-for-wallet copy', () => {
    const { rerender } = render(<ActionArea {...actionProps('approving')} />)
    expect(
      screen.getByText('Waiting for confirmation in your wallet.'),
    ).toBeInTheDocument()
    rerender(<ActionArea {...actionProps('paying')} />)
    expect(
      screen.getByText('Waiting for confirmation in your wallet.'),
    ).toBeInTheDocument()
  })

  it('tx_pending links the hash on the explorer the moment it exists', () => {
    render(<ActionArea {...actionProps('tx_pending', { payHash: HASH })} />)
    expect(screen.getByText('Transaction sent. Waiting for the network.')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /View transaction/ })
    expect(link).toHaveAttribute('href', `https://sepolia.basescan.org/tx/${HASH}`)
  })

  it('syncing keeps the explorer link and frames backend sync as bookkeeping', () => {
    render(<ActionArea {...actionProps('syncing', { payHash: HASH })} />)
    expect(
      screen.getByText("Confirmed on-chain. Updating the merchant's records."),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View transaction/ })).toBeInTheDocument()
  })

  it('rejected is recoverable with try again', () => {
    const props = actionProps('rejected')
    render(<ActionArea {...props} />)
    expect(
      screen.getByText('You canceled the request in your wallet. Nothing was sent.'),
    ).toBeInTheDocument()
    screen.getByRole('button', { name: 'Try again' }).click()
    expect(props.onRetry).toHaveBeenCalled()
  })

  it('failed shows the copy and the explorer link, and offers NO retry', () => {
    // `failed` is now reverted/terminal only: retrying the same call cannot
    // change the outcome, so offering it would be a false affordance. A
    // NETWORK failure lands on chain_unreachable instead, which does retry.
    render(<ActionArea {...actionProps('failed', { payHash: HASH })} />)
    expect(
      screen.getByText(
        'The transaction did not complete. No payment left your wallet. Check the details on the explorer.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View transaction/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('chain_unreachable is transient: network copy plus a retry, no tx claim', () => {
    const props = actionProps('chain_unreachable')
    render(<ActionArea {...props} />)
    expect(
      screen.getByText(
        'The network is not responding right now. Your payment has not started.',
      ),
    ).toBeInTheDocument()
    screen.getByRole('button', { name: 'Try again' }).click()
    expect(props.onRetry).toHaveBeenCalled()
    // No transaction exists, so nothing may be linked or claimed about one.
    expect(screen.queryByRole('link', { name: /View transaction/ })).toBeNull()
  })

  it('confirmation_unknown never says failed and always keeps the hash', () => {
    render(<ActionArea {...actionProps('confirmation_unknown', { payHash: HASH })} />)
    expect(
      screen.getByText(
        'Your transaction was sent. We cannot confirm it right now. Check it on the explorer.',
      ),
    ).toBeInTheDocument()
    // The explorer link is the payer's independent proof when we cannot help.
    expect(screen.getByRole('link', { name: /View transaction/ })).toHaveAttribute(
      'href',
      `https://sepolia.basescan.org/tx/${HASH}`,
    )
    expect(screen.queryByText(/did not complete/)).toBeNull()
    expect(screen.queryByText(/No payment left your wallet/)).toBeNull()
  })

  it('a silent wallet gets an explanation and a way out, spinner intact', () => {
    const props = actionProps('paying', { waitingLong: true })
    render(<ActionArea {...props} />)
    // The original waiting copy STAYS: the prompt is still live.
    expect(
      screen.getByText('Waiting for confirmation in your wallet.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Your wallet has not answered yet. Check for a wallet window or popup. If it says this network is not supported, you can pay with a different wallet.',
      ),
    ).toBeInTheDocument()
    screen.getByRole('button', { name: 'Use a different wallet' }).click()
    expect(props.onUseOtherWallet).toHaveBeenCalled()
  })

  it('says nothing extra before the silence window elapses', () => {
    render(<ActionArea {...actionProps('paying')} />)
    expect(screen.queryByText(/has not answered yet/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Use a different wallet' })).toBeNull()
  })

  it('NEVER offers to change wallet once a transaction exists', () => {
    // canSwitchWallet is false the moment anything has been broadcast; a
    // control that could drop the wallet mid-transaction is the wrong change.
    render(
      <ActionArea
        {...actionProps('paying', {
          waitingLong: true,
          canSwitchWallet: false,
          payHash: HASH,
        })}
      />,
    )
    expect(screen.getByText(/has not answered yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use a different wallet' })).toBeNull()
  })

  it('the approve prompt gets the same treatment', () => {
    render(<ActionArea {...actionProps('approving', { waitingLong: true })} />)
    expect(screen.getByText(/has not answered yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use a different wallet' })).toBeInTheDocument()
  })

  it('wallet_chain_unsupported blames the wallet, offers another, and claims no tx', () => {
    const props = actionProps('wallet_chain_unsupported')
    render(<ActionArea {...props} />)
    expect(
      screen.getByText(
        'This wallet does not support Base Sepolia. Nothing was sent and nothing was charged. You can pay with a different wallet.',
      ),
    ).toBeInTheDocument()
    // Never an RSends failure, and never a transaction that does not exist.
    expect(screen.queryByText(/did not complete/)).toBeNull()
    expect(screen.queryByRole('link', { name: /View transaction/ })).toBeNull()
    screen.getByRole('button', { name: 'Use a different wallet' }).click()
    expect(props.onUseOtherWallet).toHaveBeenCalled()
  })

  it('buttons are at least 44px touch targets', () => {
    render(<ActionArea {...actionProps('ready')} />)
    const button = screen.getByRole('button', { name: 'Pay 50.6 USDC' })
    // payUi buttons: 13px vertical padding + 15px font over ~1.2 line height.
    expect(button).toHaveStyle({ padding: '13px 18px', fontSize: '15px' })
  })
})

describe('terminal views (no wallet UI)', () => {
  it('success shows heading, body and the explorer link', () => {
    render(
      <SuccessView
        amount="50.6"
        currency="USDC"
        merchant="Caffe Roma"
        chainId={84532}
        txHash={HASH}
      />,
    )
    expect(screen.getByText('Payment complete')).toBeInTheDocument()
    expect(screen.getByText('You paid 50.6 USDC to Caffe Roma.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View transaction/ })).toHaveAttribute(
      'href',
      `https://sepolia.basescan.org/tx/${HASH}`,
    )
    expect(screen.queryByTestId('connect-slot')).toBeNull()
  })

  it('success keeps the paying address on screen, read-only', () => {
    render(
      <SuccessView
        amount="50.6"
        currency="USDC"
        merchant="Caffe Roma"
        chainId={84532}
        txHash={HASH}
        payer="0x1111111111111111111111111111111111111111"
      />,
    )
    expect(screen.getByText('Paid from')).toBeInTheDocument()
    expect(screen.getByText('0x1111…1111')).toBeInTheDocument()
    // Terminal card: still no wallet control of any kind.
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('expired, already paid and not found render their copy', () => {
    const { rerender } = render(<ExpiredView />)
    expect(
      screen.getByText('This payment link has expired. Ask the merchant for a new one.'),
    ).toBeInTheDocument()

    rerender(<AlreadyPaidView chainId={84532} txHash={HASH} />)
    expect(screen.getByText('This payment was already completed.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View transaction/ })).toBeInTheDocument()

    rerender(<NotFoundView />)
    expect(
      screen.getByText('We could not find this payment. Check the link and try again.'),
    ).toBeInTheDocument()
  })
})
