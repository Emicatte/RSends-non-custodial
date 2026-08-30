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

  it('normalizes routerVersion: 2 → 2, absent → 1, junk → 1', () => {
    const v2 = {
      ...RAW_BASE,
      onchain: { ...RAW_BASE.onchain, routerVersion: 2, fee: '0', total: '50000000', maxFee: null },
    }
    expect(normalizeIntent(v2, 'pi_v2').onchain!.routerVersion).toBe(2)
    // absent (pre-P3 backend) → v1
    expect(normalizeIntent(RAW_BASE, 'pi_v1').onchain!.routerVersion).toBe(1)
    // junk values never produce a v2 flow
    const junk = {
      ...RAW_BASE,
      onchain: { ...RAW_BASE.onchain, routerVersion: 99 as unknown as number },
    }
    expect(normalizeIntent(junk, 'pi_junk').onchain!.routerVersion).toBe(1)
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

describe('watch-only intents', () => {
  const RAW_TRON = {
    status: 'pending',
    expires_at: '2026-07-09T12:00:00Z',
    amount: 10.000001,
    amount_exact: '10.000001',
    currency: 'USDT',
    chain: 'TRON',
    recipient: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
    onchain: null,
  }

  it('normalizes without throwing, and without an onchain block', () => {
    // `onchain: null` is the CORRECT shape here, not a degraded one: there is
    // no contract to call. The build gate never opens, so viem's getAddress()
    // is never handed a T-address -- it would throw, and the catch around it
    // would quietly report a valid invoice as unpayable.
    const intent = normalizeIntent(RAW_TRON, 'pi_tron')
    expect(intent.onchain).toBeNull()
    expect(intent.status).toBe('pending')
  })

  it('carries the base58 recipient through byte-identical', () => {
    const intent = normalizeIntent(RAW_TRON, 'pi_tron')
    expect(intent.recipient).toBe('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')
    expect(intent.recipient).not.toBe(intent.recipient!.toLowerCase())
  })

  it('carries the exact amount and the partial figures', () => {
    const intent = normalizeIntent(
      { ...RAW_TRON, status: 'partial', amount_received: '4.5', underpaid_amount: '5.500001' },
      'pi_tron',
    )
    expect(intent.amountExact).toBe('10.000001')
    expect(intent.amountReceived).toBe('4.5')
    expect(intent.underpaidAmount).toBe('5.500001')
  })

  it('labels both TRON networks', () => {
    expect(normalizeIntent(RAW_TRON, 'x').chainLabel).toBe('TRON')
    expect(
      normalizeIntent({ ...RAW_TRON, chain: 'tron_nile' }, 'x').chainLabel,
    ).toBe('TRON Nile')
  })

  it('leaves the new fields null on an intent that omits them', () => {
    const intent = normalizeIntent(RAW_BASE, 'x')
    expect(intent.recipient).toBeNull()
    expect(intent.amountExact).toBeNull()
    expect(intent.amountReceived).toBeNull()
    expect(intent.underpaidAmount).toBeNull()
  })
})
