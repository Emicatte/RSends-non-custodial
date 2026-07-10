/**
 * lib/web3/feeMath — fee/format source of truth for the hosted checkout UI.
 *
 * The CHARGED fee is always the router's on-chain quoteFee (delivered by the
 * backend as `onchain.fee`, or self-quoted via useReadContract when
 * `feeUnavailable`). `quoteFeeMirror` is a pure mirror of the contract's
 * logic — RSendsRouter.quoteFee:
 *
 *   fee = baseFee + (threshold != 0 && amount >= threshold ? surcharge : 0)
 *
 * It exists for the parity unit test (display math vs contract math) and MUST
 * track the Solidity source; it is never used to build calldata — live quotes
 * are. `resolveFeeBreakdown` is the ONE place total/maxFee are computed:
 * the summary rows AND the transaction args (approve amount, permit value,
 * payNative value, maxFee) all consume it.
 */

import { formatUnits } from 'viem'

export interface FeeConfig {
  baseFee: bigint
  threshold: bigint
  surcharge: bigint
}

export interface FeeBreakdown {
  fee: bigint
  total: bigint
  maxFee: bigint
}

export function quoteFeeMirror(amount: bigint, config: FeeConfig): bigint {
  let fee = config.baseFee
  if (config.threshold !== 0n && amount >= config.threshold) {
    fee += config.surcharge
  }
  return fee
}

export function resolveFeeBreakdown(
  amount: bigint,
  fee: bigint | null,
): FeeBreakdown | null {
  if (fee == null) return null
  return { fee, total: amount + fee, maxFee: fee }
}

export function formatTokenAmount(value: bigint, decimals: number): string {
  return formatUnits(value, decimals)
}
