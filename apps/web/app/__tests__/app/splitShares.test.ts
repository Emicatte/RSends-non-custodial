/**
 * Pure share math for the split ("Flow") create form — lib/splitShares.ts.
 *
 * Percentages are DISPLAY ONLY; state and validation are integer basis
 * points (1% = 100 bps, contract requires an exact 10000 sum). The parser
 * is locale-safe (comma and dot both accepted as the decimal separator)
 * and rejects sub-bps precision — never silently rounds.
 */
import { percentToBps, remainderBps, bpsToPercent } from '@/lib/splitShares'

describe('percentToBps', () => {
  it('parses whole percents to bps', () => {
    expect(percentToBps('40')).toBe(4000)
    expect(percentToBps('60')).toBe(6000)
    expect(percentToBps('100')).toBe(10000)
  })

  it('parses two-decimal percents exactly', () => {
    expect(percentToBps('43.72')).toBe(4372)
    expect(percentToBps('0.01')).toBe(1)
    expect(percentToBps('99.99')).toBe(9999)
  })

  it('accepts a locale comma as the decimal separator', () => {
    expect(percentToBps('0,02')).toBe(2)
    expect(percentToBps('43,72')).toBe(4372)
  })

  it('trims surrounding whitespace', () => {
    expect(percentToBps(' 40 ')).toBe(4000)
  })

  it('rejects sub-bps precision instead of rounding', () => {
    expect(percentToBps('30.001')).toBeNull()
    expect(percentToBps('0,005')).toBeNull()
  })

  it('rejects more than one decimal separator', () => {
    expect(percentToBps('1.000,5')).toBeNull()
    expect(percentToBps('1,000.5')).toBeNull()
    expect(percentToBps('1..5')).toBeNull()
    expect(percentToBps('1,,5')).toBeNull()
  })

  it('rejects empty, zero, negative, and out-of-range values', () => {
    expect(percentToBps('')).toBeNull()
    expect(percentToBps('   ')).toBeNull()
    expect(percentToBps('0')).toBeNull()
    expect(percentToBps('-5')).toBeNull()
    expect(percentToBps('100.01')).toBeNull()
    expect(percentToBps('250')).toBeNull()
  })

  it('rejects non-numeric input', () => {
    expect(percentToBps('abc')).toBeNull()
    expect(percentToBps('40%')).toBeNull()
    expect(percentToBps('1e2')).toBeNull()
  })
})

describe('remainderBps', () => {
  it('returns 10000 minus the manual sum', () => {
    expect(remainderBps([4372])).toBe(5628)
    expect(remainderBps([4372, 3000])).toBe(2628)
    expect(remainderBps([4000, 6000 - 100])).toBe(100)
  })

  it('goes to zero or negative when the manual rows use up 100%', () => {
    expect(remainderBps([10000])).toBe(0)
    expect(remainderBps([9999, 9999])).toBe(-9998)
  })

  it('is null while any manual row is unparsed', () => {
    expect(remainderBps([4000, null])).toBeNull()
    expect(remainderBps([null])).toBeNull()
  })

  it('is 10000 for an empty manual set', () => {
    expect(remainderBps([])).toBe(10000)
  })
})

describe('bpsToPercent', () => {
  it('formats bps as a two-decimal percent string', () => {
    expect(bpsToPercent(5628)).toBe('56.28')
    expect(bpsToPercent(2)).toBe('0.02')
    expect(bpsToPercent(10000)).toBe('100.00')
  })
})
