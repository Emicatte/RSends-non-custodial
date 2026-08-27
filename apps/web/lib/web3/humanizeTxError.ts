/**
 * lib/web3/humanizeTxError.ts — map raw wallet/RPC/contract errors to friendly copy.
 *
 * Covers the cases the /pay state machine can surface: user-reject, insufficient
 * balance, insufficient allowance, the contract's FeeTooHigh / UnsupportedToken
 * custom errors, wrong-network, and generic RPC/network failures.
 */
const USER_REJECT_RE =
  /user rejected|user denied|denied (the )?(transaction|request|signature)|rejected the request/i

/** True when the error is the payer canceling in their wallet (recoverable). */
export function isUserRejection(err: unknown): boolean {
  if (err == null) return false
  const raw = err instanceof Error ? err.message : String(err)
  return USER_REJECT_RE.test(raw)
}

/**
 * True when the error means "we could not reach the chain", as opposed to
 * "the chain answered and the answer was no".
 *
 * The distinction drives what the payer is told: a transport fault is
 * transient and invites a retry, while a revert is terminal and must not.
 * Getting it wrong in the terminal direction is the serious one — it tells a
 * payer their transaction did not complete when nobody actually knows.
 *
 * The shapes below are the ones seen in the wild, including the Base Sepolia
 * fleet outage of 2026-08-22 (`-32011 no backend is currently healthy to
 * serve traffic`, surfaced by viem as `HTTP request failed. Status: 503`).
 * A revert is never in this set: `execution reverted` is an answer.
 */
const TRANSIENT_NETWORK_RE =
  /timeout|timed out|network error|fetch failed|failed to fetch|load failed|request failed|no backend|-32011|status:\s*(408|425|429|50\d)|econnrefused|econnreset|enotfound|socket hang up|connection (refused|reset|closed)|service unavailable|bad gateway|gateway timeout/i

export function isTransientNetworkError(err: unknown): boolean {
  if (err == null) return false
  const raw = err instanceof Error ? err.message : String(err)
  // An answer from the chain is never a transport fault, however it is
  // phrased — some nodes wrap a revert in an HTTP envelope.
  if (/execution reverted|reverted with|custom error/i.test(raw)) return false
  if (isUserRejection(err)) return false
  return TRANSIENT_NETWORK_RE.test(raw)
}

/**
 * True when the WALLET refuses to operate on this chain, as opposed to the
 * chain being unreachable or the payer declining.
 *
 * Observed with Coinbase Smart Wallet on Base Sepolia, which answers "Base
 * Sepolia is not supported. Try another blockchain." in its own window. The
 * distinction matters because all three of the other classifications lie
 * about it: it is not a failed payment (nothing was sent), not a transport
 * fault (the chain is fine), and not a cancellation (the payer did not
 * choose this). It is also the one case where retrying THIS wallet cannot
 * work, so the only honest remedy is a different wallet.
 *
 * `UnsupportedToken()` shares the prefix and means something else entirely —
 * an answer from the contract — so the revert guard below runs first.
 */
const UNSUPPORTED_CHAIN_RE =
  /unsupported chain|unsupported network|unrecognized chain|chainnotconfigured|switchchainerror|chain\s+"?[^"\s]+"?\s+not (configured|supported)|not configured for connector|does not support .{0,40}(chain|network)|(chain|network|blockchain)[^.]{0,40}\bis not supported|try another blockchain/i

/** EIP-1193: the wallet does not recognize the requested chain. */
const UNRECOGNIZED_CHAIN_CODE = 4902

/** Every `code` down the cause chain — viem nests the provider's error. */
function errorCodes(err: unknown): unknown[] {
  const codes: unknown[] = []
  let node: unknown = err
  for (let depth = 0; node != null && depth < 5; depth++) {
    const e = node as { code?: unknown; cause?: unknown }
    if (typeof e !== 'object') break
    if (e.code !== undefined) codes.push(e.code)
    node = e.cause
  }
  return codes
}

export function isUnsupportedChainError(err: unknown): boolean {
  if (err == null) return false
  const raw = err instanceof Error ? err.message : String(err)
  // An answer from the contract is never a wallet limitation.
  if (/execution reverted|reverted with|custom error/i.test(raw)) return false
  // Deliberately NOT gated on isUserRejection, unlike the transient check
  // above. Measured against a wallet that refuses Base Sepolia: viem wraps a
  // 4902 as UserRejectedRequestError, so `.message` READS "User rejected the
  // request." and the real cause survives only in the `Details:` line and the
  // nested code. Deferring to the rejection check there would tell the payer
  // they cancelled something they never saw — so the specific markers win,
  // and a plain rejection (which carries none of them) still falls through.
  if (errorCodes(err).includes(UNRECOGNIZED_CHAIN_CODE)) return true
  return UNSUPPORTED_CHAIN_RE.test(raw)
}

export function humanizeTxError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)

  if (isUserRejection(err)) {
    return 'Transaction rejected in wallet.'
  }
  if (/FeeTooHigh/i.test(raw)) {
    return 'The network fee changed — refresh and try again.'
  }
  if (/UnsupportedToken/i.test(raw)) {
    return "This token isn't accepted on this network."
  }
  if (/insufficient allowance|exceeds allowance/i.test(raw)) {
    return 'Token allowance too low — approve again.'
  }
  if (/insufficient funds|exceeds balance|transfer amount exceeds balance/i.test(raw)) {
    return 'Insufficient balance for the amount or gas.'
  }
  if (/chain mismatch|does not match the target chain|wrong network|chain .* not configured/i.test(raw)) {
    return 'Wrong network — switch to Base Sepolia.'
  }
  if (/timeout|timed out|network error|fetch failed|failed to fetch|request failed/i.test(raw)) {
    return 'Network error — please try again.'
  }
  // viem puts the human-readable reason on the first line.
  return raw.split('\n')[0].slice(0, 160)
}
