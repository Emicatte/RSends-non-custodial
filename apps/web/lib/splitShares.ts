// Pure share math for the split ("Flow") create form. The merchant enters
// AMOUNTS per recipient (never percentages); bps are derived from the
// amount ratios because RSendsSplitRouter takes uint16 sharesBps summing
// to EXACTLY 10000. All money math is BigInt base units (ETH's 18 decimals
// overflow Number); `onchainAmounts` mirrors the contract's
// floor-plus-remainder-to-recipient-0 rule bit for bit, so the UI preview
// equals the on-chain result by construction.

export const BPS_TOTAL = 10000

// One plain decimal number: digits with at most one dot. No sign, no
// exponent — not something a person types into an amount field.
const DECIMAL_RE = /^(?:\d+(?:\.\d*)?|\.\d+)$/

/** Amount string → base units (> 0n), or null when invalid. Locale-safe:
 * comma and dot both work as the decimal separator. Digits beyond the
 * token's decimals are REJECTED, never rounded. */
export function amountToBase(input: string, decimals: number): bigint | null {
  const trimmed = input.trim()
  if (trimmed === '') return null
  const separators = trimmed.match(/[.,]/g)
  if (separators && separators.length > 1) return null
  const normalized = trimmed.replace(',', '.')
  if (!DECIMAL_RE.test(normalized)) return null
  const [whole = '', frac = ''] = normalized.split('.')
  if (frac.length > decimals) return null
  const base = BigInt(whole || '0') * 10n ** BigInt(decimals) + BigInt(frac.padEnd(decimals, '0') || '0')
  return base > 0n ? base : null
}

/** Base units → human amount string, trailing zeros stripped. Display only. */
export function formatBase(value: bigint, decimals: number): string {
  const scale = 10n ** BigInt(decimals)
  const whole = value / scale
  const frac = (value % scale).toString().padStart(decimals, '0').replace(/0+$/, '')
  return frac ? `${whole}.${frac}` : whole.toString()
}

/** Base units left for the balance row: total − sum(manual rows). Null
 * while any manual row is unparsed; zero or negative when the manual rows
 * already use up the total (the caller treats that as over-allocated). */
export function remainderBase(
  totalBase: bigint,
  manualBase: Array<bigint | null>,
): bigint | null {
  let sum = 0n
  for (const base of manualBase) {
    if (base == null) return null
    sum += base
  }
  return totalBase - sum
}

/** Amount vector (summing to the total) → uint16 sharesBps summing to
 * EXACTLY 10000. Legs 1..n−1 round half-up; leg 0 absorbs the ±bps drift —
 * the same leg the contract's remainder rule favors. Null when the vector
 * is not a valid split (fewer than 2 legs, a non-positive amount, sum ≠
 * total, or a leg too small to represent as at least 1 bps). */
export function amountsToSharesBps(
  amountsBase: bigint[],
  totalBase: bigint,
): number[] | null {
  const n = amountsBase.length
  if (n < 2 || totalBase <= 0n) return null
  let sum = 0n
  for (const a of amountsBase) {
    if (a <= 0n) return null
    sum += a
  }
  if (sum !== totalBase) return null
  const shares = new Array<number>(n)
  let allocated = 0
  for (let i = 1; i < n; i++) {
    // Exact half-up rounding of a·10000/total in BigInt.
    const bps = Number((amountsBase[i] * 20000n + totalBase) / (2n * totalBase))
    if (bps < 1) return null
    shares[i] = bps
    allocated += bps
  }
  const first = BPS_TOTAL - allocated
  if (first < 1) return null
  shares[0] = first
  return shares
}

/** The contract mirror (RSendsSplitRouter._computeAmounts): per-leg
 * floor(total·bps/10000), division remainder added to recipient 0. */
export function onchainAmounts(totalBase: bigint, sharesBps: number[]): bigint[] {
  const amounts = sharesBps.map((bps) => (totalBase * BigInt(bps)) / 10000n)
  const allocated = amounts.reduce((acc, a) => acc + a, 0n)
  amounts[0] += totalBase - allocated
  return amounts
}
