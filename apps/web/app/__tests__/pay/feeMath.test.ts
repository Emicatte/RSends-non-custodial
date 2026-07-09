/**
 * lib/web3/feeMath — the single fee/format source of truth for the hosted
 * checkout UI.
 *
 * quoteFeeMirror is a pure mirror of RSendsRouter.quoteFee:
 *   fee = baseFee + (threshold != 0 && amount >= threshold ? surcharge : 0)
 * Parity is asserted against the deployed Base Sepolia USDC feeConfig
 * (baseFee 600000, threshold 1000000000, surcharge 2400000 — 6-decimal base
 * units) below, at, and above the threshold. The UI never reimplements fee
 * math elsewhere: display rows and calldata args both flow through
 * resolveFeeBreakdown.
 */
import {
  formatTokenAmount,
  quoteFeeMirror,
  resolveFeeBreakdown,
} from '@/lib/web3/feeMath'

// Deployed Base Sepolia USDC feeConfig (base units, 6 decimals).
const USDC_CONFIG = {
  baseFee: 600_000n, // 0.60
  threshold: 1_000_000_000n, // 1000
  surcharge: 2_400_000n, // 2.40 -> 3.00 at/above threshold
}

describe('quoteFeeMirror (contract parity)', () => {
  it('charges the base fee below the threshold', () => {
    expect(quoteFeeMirror(1_000_000n, USDC_CONFIG)).toBe(600_000n) // 1 USDC
    expect(quoteFeeMirror(999_990_000n, USDC_CONFIG)).toBe(600_000n) // 999.99
  })

  it('adds the surcharge exactly at the threshold (contract uses >=)', () => {
    expect(quoteFeeMirror(1_000_000_000n, USDC_CONFIG)).toBe(3_000_000n)
  })

  it('adds the surcharge above the threshold', () => {
    expect(quoteFeeMirror(1_500_000_000n, USDC_CONFIG)).toBe(3_000_000n)
    expect(quoteFeeMirror(123_456_789_000n, USDC_CONFIG)).toBe(3_000_000n)
  })

  it('threshold = 0 disables the surcharge entirely', () => {
    const cfg = { ...USDC_CONFIG, threshold: 0n }
    expect(quoteFeeMirror(999_999_999_999n, cfg)).toBe(600_000n)
  })

  it('amount 0 still charges the base fee (contract semantics)', () => {
    expect(quoteFeeMirror(0n, USDC_CONFIG)).toBe(600_000n)
  })
})

describe('resolveFeeBreakdown', () => {
  it('computes total = amount + fee and maxFee = fee', () => {
    const breakdown = resolveFeeBreakdown(50_000_000n, 600_000n)
    expect(breakdown).toEqual({
      fee: 600_000n,
      total: 50_600_000n,
      maxFee: 600_000n,
    })
  })

  it('returns null while the fee is unknown (quote still loading)', () => {
    expect(resolveFeeBreakdown(50_000_000n, null)).toBeNull()
  })
})

describe('formatTokenAmount', () => {
  it('formats with per-token decimals', () => {
    expect(formatTokenAmount(50_600_000n, 6)).toBe('50.6')
    expect(formatTokenAmount(600_000n, 6)).toBe('0.6')
    expect(formatTokenAmount(1_000_000_000_000_000_000n, 18)).toBe('1')
  })

  it('keeps full precision (no rounding of base units)', () => {
    expect(formatTokenAmount(1n, 6)).toBe('0.000001')
    expect(formatTokenAmount(123_456_789n, 6)).toBe('123.456789')
  })
})
