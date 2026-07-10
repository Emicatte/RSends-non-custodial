/**
 * lib/web3/checkoutState — the pure state deriver for the hosted checkout.
 *
 * One function owns the page's wallet-flow state machine; the central hook
 * (useHostedCheckout) collects flags from wagmi and this deriver decides the
 * step. Terminal INTENT states (expired / already paid / not found) are
 * handled upstream at page level and never reach this function.
 *
 * Precedence, top to bottom (each branch documented by a test):
 *   payment outcome (success/syncing/failed) > in-flight tx > wallet prompts
 *   > rejection > connection > network > quoting > balance > allowance.
 * Outcome outranks connection/network so that disconnecting or switching
 * chains AFTER paying can never hide the result.
 */

import type { Hex } from 'viem'

export type CheckoutStep =
  | 'connect'
  | 'wrong_network'
  | 'quoting'
  | 'insufficient_balance'
  | 'needs_approve'
  | 'approving'
  | 'approve_pending'
  | 'ready_to_pay'
  | 'ready'
  | 'paying'
  | 'tx_pending'
  | 'syncing'
  | 'success'
  | 'rejected'
  | 'failed'

export interface CheckoutInputs {
  isConnected: boolean
  onCorrectChain: boolean
  /** eip2612 token: single signature + payWithPermit, no approve step ever */
  usesPermit: boolean
  isNative: boolean
  fee: bigint | null
  total: bigint | null
  /** payer's token (or native) balance; null while unknown — never blocks */
  balance: bigint | null
  /** current allowance, approve+pay path only */
  allowance: bigint | null
  /** permit prerequisites (nonce + domain name) loaded */
  permitReady: boolean
  approvePromptOpen: boolean
  approveHash: Hex | string | null
  approveConfirmed: boolean
  /** wallet prompt open for the pay tx OR the permit signature */
  payPromptOpen: boolean
  payHash: Hex | string | null
  payMined: boolean
  payReverted: boolean
  /** the send itself errored before a hash existed (non-rejection) */
  sendFailed: boolean
  userRejected: boolean
  /** backend reflects the payment (indexer caught up) */
  backendPaid: boolean
}

export function deriveCheckoutStep(i: CheckoutInputs): CheckoutStep {
  // ── Payment outcome: outranks everything, including connection ──
  if (i.payReverted || i.sendFailed) return 'failed'
  if (i.payMined) return i.backendPaid ? 'success' : 'syncing'
  if (i.payHash) return 'tx_pending'

  // ── Wallet prompts / recoverable cancel ──
  if (i.payPromptOpen) return 'paying'
  if (i.approvePromptOpen) return 'approving'
  if (i.userRejected) return 'rejected'
  if (i.approveHash && !i.approveConfirmed) return 'approve_pending'

  // ── Session prerequisites ──
  if (!i.isConnected) return 'connect'
  if (!i.onCorrectChain) return 'wrong_network'
  if (i.fee == null || i.total == null || (i.usesPermit && !i.permitReady)) {
    return 'quoting'
  }
  if (i.balance != null && i.balance < i.total) return 'insufficient_balance'

  // ── Approve+pay fallback path only (never for permit or native) ──
  if (!i.usesPermit && !i.isNative && (i.allowance ?? 0n) < i.total) {
    return 'needs_approve'
  }
  if (i.approveConfirmed) return 'ready_to_pay'
  return 'ready'
}
