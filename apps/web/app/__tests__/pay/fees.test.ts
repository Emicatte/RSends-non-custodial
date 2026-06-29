import {
  computeFeeEUR, BASE_FEE_EUR, FEE_CAP_EUR, CAP_THRESHOLD_EUR,
} from '@/lib/fees'

describe('computeFeeEUR (display-only EUR estimate)', () => {
  it('exposes the spec constants', () => {
    expect(BASE_FEE_EUR).toBe(0.15)
    expect(FEE_CAP_EUR).toBe(1.15)
    expect(CAP_THRESHOLD_EUR).toBe(1000)
  })

  it('is the flat base fee below the threshold', () => {
    expect(computeFeeEUR(50)).toBe(0.15)
    expect(computeFeeEUR(999.99)).toBe(0.15)
  })

  it('steps up to the cap at/above the threshold', () => {
    expect(computeFeeEUR(1000)).toBe(1.15)
    expect(computeFeeEUR(1500)).toBe(1.15)
  })

  it('falls back to the base fee for non-positive / invalid input', () => {
    expect(computeFeeEUR(0)).toBe(0.15)
    expect(computeFeeEUR(-5)).toBe(0.15)
    expect(computeFeeEUR(NaN)).toBe(0.15)
  })
})
