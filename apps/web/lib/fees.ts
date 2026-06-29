/**
 * lib/fees.ts — DISPLAY-ONLY EUR fee estimate.
 *
 * ⚠️ The CHARGED fee is always the on-chain `quoteFee(token, amount)` from
 * RSendsRouter (token base units, no live FX). This module exists only to show a
 * human EUR-equivalent in the UI and as a fallback estimate when the on-chain
 * quote hasn't loaded. NEVER use it to build calldata or to set `maxFee`.
 *
 * The constants mirror the deployed Base Sepolia USDC feeConfig (baseFee 0.15,
 * threshold 1000, surcharge 1.00) so the EUR estimate tracks what's charged.
 */
export const BASE_FEE_EUR = 0.15
export const FEE_CAP_EUR = 1.15
export const CAP_THRESHOLD_EUR = 1000

export function computeFeeEUR(principalEUR: number): number {
  // CONFIRM TIER LOGIC — flat €0.15 per tx; at/above the €1,000 threshold the
  // fee steps up to the €1.15 cap (baseFee + surcharge). Never a % of volume.
  // This is the one rule to double-check with the founder.
  if (!Number.isFinite(principalEUR) || principalEUR <= 0) return BASE_FEE_EUR
  return principalEUR >= CAP_THRESHOLD_EUR ? FEE_CAP_EUR : BASE_FEE_EUR
}
