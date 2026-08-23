/**
 * lib/web3/checkoutState — the pure state deriver for the hosted checkout.
 *
 * One function owns the page's wallet-flow state machine; the central hook
 * (useHostedCheckout) collects flags from wagmi and this deriver decides the
 * step. Terminal INTENT states (expired / already paid / not found) are
 * handled upstream at page level and never reach this function.
 *
 * Precedence, top to bottom (each branch documented by a test):
 *   payment outcome (success/syncing/failed/confirmation_unknown) >
 *   in-flight tx > wallet prompts > rejection > connection > network >
 *   chain reachability > quoting > balance > allowance.
 * Outcome outranks connection/network so that disconnecting or switching
 * chains AFTER paying can never hide the result.
 *
 * Two of the steps exist because the chain itself can stop answering
 * (Base Sepolia, 2026-08-22). The rules they encode:
 *   - a transaction that was SENT but cannot be read is UNKNOWN, never
 *     failed. Telling a payer their money is gone when it is not is the
 *     worst error this product can make;
 *   - a transport fault is transient and invites a retry; a revert is
 *     terminal and must not.
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
  /** the chain cannot be read, and NO transaction exists — transient, retry */
  | 'chain_unreachable'
  /** a transaction was sent and its receipt cannot be read — outcome unknown */
  | 'confirmation_unknown'

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
  /** ...and that send error was a transport fault, so it may yet succeed */
  sendFailedTransient: boolean
  /** a read required to BUILD the transaction failed (fee/allowance/permit) */
  chainUnreachable: boolean
  /** the receipt of an already-sent tx could not be read */
  receiptUnreadable: boolean
  userRejected: boolean
  /** backend reflects the payment (indexer caught up) */
  backendPaid: boolean
}

export function deriveCheckoutStep(i: CheckoutInputs): CheckoutStep {
  // ── Payment outcome: outranks everything, including connection ──
  if (i.payReverted) return 'failed'
  if (i.payMined) return i.backendPaid ? 'success' : 'syncing'
  // A sent transaction whose receipt we cannot read: the chain knows the
  // answer and we do not. Anything else here would be a claim we cannot back.
  // Below the real outcomes above — once a receipt HAS been read, a stale
  // read error must never turn a settled payment back into "unknown" — and
  // above tx_pending, because an endless spinner is not an answer either.
  if (i.payHash && i.receiptUnreadable) return 'confirmation_unknown'
  if (i.payHash) return 'tx_pending'
  // No hash exists, so nothing was broadcast: a transport fault here is
  // retryable, and only a real rejection from the chain is terminal.
  if (i.sendFailedTransient) return 'chain_unreachable'
  if (i.sendFailed) return 'failed'

  // ── Wallet prompts / recoverable cancel ──
  if (i.payPromptOpen) return 'paying'
  if (i.approvePromptOpen) return 'approving'
  if (i.userRejected) return 'rejected'
  if (i.approveHash && !i.approveConfirmed) return 'approve_pending'

  // ── Session prerequisites ──
  if (!i.isConnected) return 'connect'
  if (!i.onCorrectChain) return 'wrong_network'
  // Before `quoting`: a read that FAILED is indistinguishable from one still
  // in flight by its data alone, and reporting "quoting" for an unreachable
  // chain is what left the payer on an endless spinner in the outage.
  if (i.chainUnreachable) return 'chain_unreachable'
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
