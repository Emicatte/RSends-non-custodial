// Pure share math for the split ("Flow") create form. Percentages are
// display only — state, validation, and the payload are integer basis
// points, because RSendsSplitRouter takes uint16 sharesBps summing to
// EXACTLY 10000 (sub-bps values are unrepresentable on-chain).

export const BPS_TOTAL = 10000

// One plain decimal number: digits with at most one dot. No sign, no
// exponent — "1e2" is not something a person types into a percent field.
const DECIMAL_RE = /^(?:\d+(?:\.\d*)?|\.\d+)$/

/** Percent string → integer bps (1..10000), or null when invalid.
 * Locale-safe: comma and dot both work as the decimal separator.
 * Sub-bps precision (e.g. "30.001") is REJECTED, never rounded. */
export function percentToBps(percent: string): number | null {
  const trimmed = percent.trim()
  if (trimmed === '') return null
  const separators = trimmed.match(/[.,]/g)
  if (separators && separators.length > 1) return null
  const normalized = trimmed.replace(',', '.')
  if (!DECIMAL_RE.test(normalized)) return null
  const value = Number(normalized)
  if (!Number.isFinite(value) || value <= 0) return null
  const bps = Math.round(value * 100)
  if (Math.abs(value * 100 - bps) > 0.001) return null
  if (bps < 1 || bps > BPS_TOTAL) return null
  return bps
}

/** Bps left for the balance row: 10000 − sum(manual rows). Null while any
 * manual row is unparsed; zero or negative when the manual rows already
 * use up 100% (the caller treats that as the over-allocated state). */
export function remainderBps(manualBps: Array<number | null>): number | null {
  let sum = 0
  for (const bps of manualBps) {
    if (bps == null) return null
    sum += bps
  }
  return BPS_TOTAL - sum
}

/** Integer bps → two-decimal percent string, for display only. */
export function bpsToPercent(bps: number): string {
  return (bps / 100).toFixed(2)
}
