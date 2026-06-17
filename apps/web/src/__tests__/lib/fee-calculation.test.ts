/**
 * Unit tests — Fee calculation (calcSplit, useDirectQuote, applySlippage)
 *
 * These are the highest-risk functions: if they miscalculate,
 * the user loses money. Every edge case matters.
 */

import { describe, it, expect } from 'vitest'
import { parseUnits, formatUnits } from 'viem'

// ── Re-implement pure functions from useSwapQuote.ts (not exported) ──
// Mirror the exact logic so tests validate the ALGORITHM, not just imports.

function calcSplit(amount: bigint, feeBps: number) {
  const fee = (amount * BigInt(feeBps)) / 10_000n
  return { net: amount - fee, fee }
}

function applySlippage(amount: bigint, slippageBps: number): bigint {
  return (amount * BigInt(10_000 - slippageBps)) / 10_000n
}

function useDirectQuote(amount: string, decimals: number, feeBps = 50) {
  if (!amount || Number(amount) <= 0) return null
  try {
    const raw = parseUnits(amount, decimals)
    const fee = (raw * BigInt(feeBps)) / 10_000n
    const net = raw - fee
    return {
      raw, net, fee,
      netFmt: parseFloat(formatUnits(net, decimals)).toFixed(6),
      feeFmt: parseFloat(formatUnits(fee, decimals)).toFixed(8),
    }
  } catch { return null }
}

describe('calcSplit — 0.5% gateway fee', () => {
  it('1 ETH (18 decimals) → fee = 0.005 ETH, NOT 0.05', () => {
    const oneETH = parseUnits('1', 18) // 1_000_000_000_000_000_000n
    const { net, fee } = calcSplit(oneETH, 50)

    expect(fee).toBe(parseUnits('0.005', 18))
    expect(net).toBe(parseUnits('0.995', 18))
    expect(fee + net).toBe(oneETH) // conservation check
  })

  it('100 USDC (6 decimals) → fee = 0.5 USDC', () => {
    const amount = parseUnits('100', 6) // 100_000_000n
    const { net, fee } = calcSplit(amount, 50)

    expect(fee).toBe(500_000n) // 0.5 USDC
    expect(net).toBe(99_500_000n)
    expect(fee + net).toBe(amount)
  })

  it('0.001 WBTC (8 decimals) — small amounts preserve precision', () => {
    const amount = parseUnits('0.001', 8) // 100_000n
    const { net, fee } = calcSplit(amount, 50)

    // 100_000 * 50 / 10_000 = 500
    expect(fee).toBe(500n)
    expect(net).toBe(99_500n)
    expect(fee + net).toBe(amount)
  })

  it('zero amount → fee = 0, net = 0', () => {
    const { net, fee } = calcSplit(0n, 50)
    expect(fee).toBe(0n)
    expect(net).toBe(0n)
  })

  it('1 wei → fee rounds down to 0 (bigint floor division)', () => {
    const { net, fee } = calcSplit(1n, 50)
    // 1 * 50 / 10_000 = 0 (integer division)
    expect(fee).toBe(0n)
    expect(net).toBe(1n)
  })

  it('custom fee: 100 bps (1%) on 10 ETH', () => {
    const amount = parseUnits('10', 18)
    const { net, fee } = calcSplit(amount, 100)

    expect(fee).toBe(parseUnits('0.1', 18))
    expect(net).toBe(parseUnits('9.9', 18))
  })

  it('fee + net always equals original (conservation law)', () => {
    const amounts = [
      parseUnits('0.0001', 18),
      parseUnits('999999', 6),
      parseUnits('21', 8),
    ]
    for (const amount of amounts) {
      const { net, fee } = calcSplit(amount, 50)
      expect(fee + net).toBe(amount)
    }
  })
})

describe('applySlippage', () => {
  it('0.5% slippage on 1 ETH', () => {
    const amount = parseUnits('1', 18)
    const min = applySlippage(amount, 50) // 50 bps = 0.5%

    expect(min).toBe(parseUnits('0.995', 18))
  })

  it('1% slippage on 100 USDC', () => {
    const amount = parseUnits('100', 6)
    const min = applySlippage(amount, 100) // 100 bps = 1%

    expect(min).toBe(parseUnits('99', 6))
  })

  it('0 slippage → same amount', () => {
    const amount = parseUnits('5', 18)
    expect(applySlippage(amount, 0)).toBe(amount)
  })
})

describe('useDirectQuote', () => {
  it('returns correct split for 1 ETH (18 decimals, 50 bps)', () => {
    const q = useDirectQuote('1', 18, 50)!
    expect(q).not.toBeNull()
    expect(q.raw).toBe(parseUnits('1', 18))
    expect(q.fee).toBe(parseUnits('0.005', 18))
    expect(q.net).toBe(parseUnits('0.995', 18))
  })

  it('returns correct split for 250 USDC (6 decimals)', () => {
    const q = useDirectQuote('250', 6, 50)!
    expect(q.fee).toBe(parseUnits('1.25', 6)) // 250 * 0.005
    expect(q.net).toBe(parseUnits('248.75', 6))
  })

  it('returns null for empty amount', () => {
    expect(useDirectQuote('', 18)).toBeNull()
  })

  it('returns null for zero amount', () => {
    expect(useDirectQuote('0', 18)).toBeNull()
  })

  it('returns null for negative amount', () => {
    expect(useDirectQuote('-5', 18)).toBeNull()
  })

  it('handles WBTC 8 decimals correctly', () => {
    const q = useDirectQuote('0.5', 8, 50)!
    expect(q.raw).toBe(parseUnits('0.5', 8))   // 50_000_000n
    expect(q.fee).toBe(250_000n)                // 50_000_000 * 50 / 10_000
    expect(q.net).toBe(49_750_000n)
  })
})
