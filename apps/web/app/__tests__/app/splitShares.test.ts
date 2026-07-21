/**
 * Pure share math for the split ("Flow") create form — lib/splitShares.ts.
 *
 * The merchant enters AMOUNTS per recipient (never percentages); bps are
 * derived from the amount ratios for the contract, which takes uint16
 * sharesBps summing to EXACTLY 10000. All money math is BigInt base units
 * (ETH's 18 decimals overflow Number) with locale-safe parsing (comma and
 * dot). `onchainAmounts` mirrors the contract's floor + remainder-to-
 * recipient-0 rule bit for bit, so the UI preview equals the on-chain
 * result by construction.
 */
import {
  amountToBase,
  formatBase,
  remainderBase,
  amountsToSharesBps,
  onchainAmounts,
} from '@/lib/splitShares'

const USDC = 6
const M = 1_000_000n // one whole USDC in base units

describe('amountToBase', () => {
  it('parses whole and fractional amounts to base units', () => {
    expect(amountToBase('30', USDC)).toBe(30n * M)
    expect(amountToBase('6', USDC)).toBe(6n * M)
    expect(amountToBase('0.01', USDC)).toBe(10_000n)
    expect(amountToBase('10.50', USDC)).toBe(10_500_000n)
  })

  it('accepts a locale comma as the decimal separator', () => {
    expect(amountToBase('0,02', USDC)).toBe(20_000n)
    expect(amountToBase('24,5', USDC)).toBe(24_500_000n)
  })

  it('trims surrounding whitespace', () => {
    expect(amountToBase(' 24 ', USDC)).toBe(24n * M)
  })

  it('handles 18-decimal tokens beyond Number precision', () => {
    expect(amountToBase('0.000000000000000001', 18)).toBe(1n)
    expect(amountToBase('1.5', 18)).toBe(1_500_000_000_000_000_000n)
  })

  it('rejects more fractional digits than the token supports', () => {
    expect(amountToBase('0.0000001', USDC)).toBeNull()
    expect(amountToBase('1.1234567', USDC)).toBeNull()
  })

  it('rejects more than one decimal separator', () => {
    expect(amountToBase('1.000,5', USDC)).toBeNull()
    expect(amountToBase('1,000.5', USDC)).toBeNull()
    expect(amountToBase('1..5', USDC)).toBeNull()
  })

  it('rejects empty, zero, negative, and non-numeric input', () => {
    expect(amountToBase('', USDC)).toBeNull()
    expect(amountToBase('   ', USDC)).toBeNull()
    expect(amountToBase('0', USDC)).toBeNull()
    expect(amountToBase('0.000', USDC)).toBeNull()
    expect(amountToBase('-5', USDC)).toBeNull()
    expect(amountToBase('abc', USDC)).toBeNull()
    expect(amountToBase('1e2', USDC)).toBeNull()
  })
})

describe('formatBase', () => {
  it('renders base units as a human amount, trailing zeros stripped', () => {
    expect(formatBase(24n * M, USDC)).toBe('24')
    expect(formatBase(9_999_000n, USDC)).toBe('9.999')
    expect(formatBase(20_001_000n, USDC)).toBe('20.001')
    expect(formatBase(10_000n, USDC)).toBe('0.01')
    expect(formatBase(0n, USDC)).toBe('0')
    expect(formatBase(1_500_000_000_000_000_000n, 18)).toBe('1.5')
  })
})

describe('remainderBase', () => {
  it('returns total minus the manual sum', () => {
    expect(remainderBase(30n * M, [6n * M])).toBe(24n * M)
    expect(remainderBase(30n * M, [10n * M, 10n * M])).toBe(10n * M)
  })

  it('goes to zero or negative when the manual rows use up the total', () => {
    expect(remainderBase(30n * M, [30n * M])).toBe(0n)
    expect(remainderBase(30n * M, [40n * M])).toBe(-10n * M)
  })

  it('is null while any manual row is unparsed', () => {
    expect(remainderBase(30n * M, [6n * M, null])).toBeNull()
    expect(remainderBase(30n * M, [null])).toBeNull()
  })

  it('is the whole total for an empty manual set', () => {
    expect(remainderBase(30n * M, [])).toBe(30n * M)
  })
})

describe('amountsToSharesBps', () => {
  it('maps clean fractions to exact bps', () => {
    expect(amountsToSharesBps([6n * M, 24n * M], 30n * M)).toEqual([2000, 8000])
    expect(amountsToSharesBps([15n * M, 15n * M], 30n * M)).toEqual([5000, 5000])
  })

  it('absorbs the rounding on recipient 0 and always sums to 10000', () => {
    // 10/30 and 20/30 are not clean bps fractions.
    expect(amountsToSharesBps([10n * M, 20n * M], 30n * M)).toEqual([3333, 6667])
    // Three-way even split: legs 1..n-1 round to 3333 each, leg 0 takes 3334.
    expect(amountsToSharesBps([10n * M, 10n * M, 10n * M], 30n * M)).toEqual([
      3334, 3333, 3333,
    ])
  })

  it('is null when an amount is too small to represent as at least 1 bps', () => {
    expect(amountsToSharesBps([1n, 30n * M - 1n], 30n * M)).toBeNull()
  })

  it('is null when amounts do not sum to the total', () => {
    expect(amountsToSharesBps([6n * M, 20n * M], 30n * M)).toBeNull()
  })

  it('is null for fewer than two legs or non-positive amounts', () => {
    expect(amountsToSharesBps([30n * M], 30n * M)).toBeNull()
    expect(amountsToSharesBps([0n, 30n * M], 30n * M)).toBeNull()
  })
})

describe('onchainAmounts', () => {
  it('mirrors the contract: per-leg floor, remainder to recipient 0', () => {
    // The ≈ case: typed 10/20 of 30 lands at 9.999 / 20.001 on-chain.
    expect(onchainAmounts(30n * M, [3333, 6667])).toEqual([9_999_000n, 20_001_000n])
    // Clean fractions come back exact.
    expect(onchainAmounts(30n * M, [2000, 8000])).toEqual([6n * M, 24n * M])
    // Pinned by the contract test: total 101, [3333,3333,3334] → [35,33,33].
    expect(onchainAmounts(101n, [3333, 3333, 3334])).toEqual([35n, 33n, 33n])
  })

  it('conserves the total for any share vector', () => {
    const shares = [3334, 3333, 3333]
    const legs = onchainAmounts(12_345_679n, shares)
    expect(legs.reduce((acc, a) => acc + a, 0n)).toBe(12_345_679n)
  })
})
