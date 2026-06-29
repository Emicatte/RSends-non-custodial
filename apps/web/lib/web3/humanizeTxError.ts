/**
 * lib/web3/humanizeTxError.ts — map raw wallet/RPC/contract errors to friendly copy.
 *
 * Covers the cases the /pay state machine can surface: user-reject, insufficient
 * balance, insufficient allowance, the contract's FeeTooHigh / UnsupportedToken
 * custom errors, wrong-network, and generic RPC/network failures.
 */
export function humanizeTxError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)

  if (/user rejected|user denied|denied (the )?(transaction|request|signature)|rejected the request/i.test(raw)) {
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
