/**
 * Hosted-checkout presentational components: per-state copy (the throwing
 * intl mock doubles as a missing-key guard), DM Mono on every numeric or
 * technical value, explorer hrefs from the central chain config, >=44px
 * touch targets, tx hash visible from the moment it exists, and terminal
 * views without any wallet UI.
 */
import { render, screen } from '@testing-library/react'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())

import { GasNote, TotalHeadline } from '@/app/pay/[intentId]/_components/SummarySection'
import { TrustFooter } from '@/app/pay/[intentId]/_components/TrustFooter'
import { ActionArea } from '@/app/pay/[intentId]/_components/ActionArea'
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
    onSwitch: jest.fn(),
    onApprove: jest.fn(),
    onPay: jest.fn(),
    onRetry: jest.fn(),
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

  it('failed shows the copy, the explorer link and try again', () => {
    render(<ActionArea {...actionProps('failed', { payHash: HASH })} />)
    expect(
      screen.getByText(
        'The transaction did not complete. No payment left your wallet. Check the details on the explorer.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View transaction/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
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
