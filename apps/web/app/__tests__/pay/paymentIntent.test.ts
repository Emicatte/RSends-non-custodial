/**
 * lib/web3/paymentIntent — normalization of the public payment-intent payload
 * plus the terminal-state mapping the hosted checkout renders BEFORE any
 * wallet UI.
 */
import {
  formatCountdown,
  merchantName,
  normalizeIntent,
  terminalKind,
} from '@/lib/web3/paymentIntent'

const RAW_BASE = {
  status: 'pending',
  expires_at: '2026-07-09T12:00:00Z',
  amount: 50,
  currency: 'USDC',
  chain: 'BASE_SEPOLIA',
  merchant_name: 'Caffe Roma',
  onchain: {
    invoiceId: '0x' + 'ab'.repeat(32),
    merchant: '0x2ec353815f2cd382628d0d399f8d80959c1758ca',
    token: '0x036cbd53842c5426634e7929541ec2318f3dcf7e',
    amount: '50000000',
    fee: '600000',
    total: '50600000',
    maxFee: '600000',
    chainId: 84532,
    router: '0x2ec353815f2cd382628d0d399f8d80959c1758ca',
    function: 'pay',
    decimals: 6,
    isNative: false,
    permitType: 'eip2612',
    permitVersion: '2',
    feeUnavailable: false,
  },
}

describe('normalizeIntent', () => {
  it('builds a typed onchain block from the nested payload', () => {
    const intent = normalizeIntent(RAW_BASE, 'pi_x')
    expect(intent.intentId).toBe('pi_x')
    expect(intent.chainLabel).toBe('Base Sepolia')
    expect(intent.onchain).not.toBeNull()
    expect(intent.onchain!.amount).toBe(50_000_000n)
    expect(intent.onchain!.fee).toBe(600_000n)
    expect(intent.onchain!.decimals).toBe(6)
    expect(intent.onchain!.chainId).toBe(84532)
    expect(intent.onchain!.permitType).toBe('eip2612')
    expect(intent.onchain!.permitVersion).toBe('2')
    // addresses are checksummed
    expect(intent.onchain!.merchant).toBe(
      '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA',
    )
  })

  it('falls back to top-level camelCase fields (alternate shape)', () => {
    const { onchain: _nested, ...rest } = RAW_BASE
    const intent = normalizeIntent(
      {
        ...rest,
        invoiceId: '0x' + 'cd'.repeat(32),
        merchant: RAW_BASE.onchain.merchant,
        token: RAW_BASE.onchain.token,
        amount_base_units: '75000000',
        chainId: 84532,
        router: RAW_BASE.onchain.router,
      },
      'pi_y',
    )
    expect(intent.onchain).not.toBeNull()
    expect(intent.onchain!.amount).toBe(75_000_000n)
    expect(intent.onchain!.fee).toBeNull() // no fee in the alternate shape
    expect(intent.onchain!.decimals).toBe(18) // default when absent
    expect(intent.onchain!.permitType).toBe('none') // default policy
  })

  it('fee null when the backend flags feeUnavailable', () => {
    const raw = {
      ...RAW_BASE,
      onchain: { ...RAW_BASE.onchain, fee: null, total: null, feeUnavailable: true },
    }
    expect(normalizeIntent(raw, 'pi_z').onchain!.fee).toBeNull()
  })

  it('malformed on-chain fields degrade to onchain: null', () => {
    const raw = {
      ...RAW_BASE,
      onchain: { ...RAW_BASE.onchain, merchant: 'not-an-address' },
    }
    expect(normalizeIntent(raw, 'pi_bad').onchain).toBeNull()
  })

  it('surfaces the settlement tx hash (matched first)', () => {
    expect(
      normalizeIntent({ ...RAW_BASE, matched_tx_hash: '0xm', tx_hash: '0xt' }, 'x')
        .txHash,
    ).toBe('0xm')
    expect(
      normalizeIntent({ ...RAW_BASE, tx_hash: '0xt' }, 'x').txHash,
    ).toBe('0xt')
  })
})

describe('terminalKind', () => {
  it('maps paid/completed to already_paid', () => {
    expect(terminalKind('paid')).toBe('already_paid')
    expect(terminalKind('completed')).toBe('already_paid')
  })

  it('maps expired/cancelled to expired', () => {
    expect(terminalKind('expired')).toBe('expired')
    expect(terminalKind('cancelled')).toBe('expired')
  })

  it('pending is not terminal', () => {
    expect(terminalKind('pending')).toBeNull()
  })

  it('post-settlement statuses without payer copy map to already_paid (pinned)', () => {
    for (const status of ['review', 'refunded', 'partial', 'overpaid']) {
      expect(terminalKind(status)).toBe('already_paid')
    }
  })
})

describe('merchantName / formatCountdown', () => {
  it('prefers the server-derived public display name', () => {
    expect(merchantName(normalizeIntent(RAW_BASE, 'x'))).toBe('Caffe Roma')
  })

  it('falls back to a neutral label', () => {
    expect(
      merchantName(normalizeIntent({ ...RAW_BASE, merchant_name: null }, 'x')),
    ).toBe('RSends Payment')
  })

  it('formats a MM:SS countdown', () => {
    expect(formatCountdown(0)).toBe('0:00')
    expect(formatCountdown(-5)).toBe('0:00')
    expect(formatCountdown(61_000)).toBe('1:01')
    expect(formatCountdown(29 * 60_000 + 5_000)).toBe('29:05')
  })
})
