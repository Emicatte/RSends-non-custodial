/**
 * lib/web3/tron/tronErrors — the single normaliser between the TRON wallet
 * adapters and the checkout state machine.
 *
 * WHY ONE FUNCTION, AND WHY IT IS DEFENSIVE. The adapters do not reject with
 * one kind of value. Most paths throw a typed `WalletError` subclass, which is
 * the good case and is classified by CLASS here rather than by message. But the
 * base `Adapter.switchChain` does:
 *
 *     Promise.reject("The current wallet doesn't support switch chain.")
 *
 * a bare string. `WalletConnectAdapter` never overrides `switchChain`, so that
 * is precisely what the WalletConnect path rejects with — meaning the single
 * path this module most needs to describe is the one where `err.message` is
 * `undefined` and `err instanceof Error` is false. Injected providers add a
 * third shape, rejecting with plain objects carrying `code`/`message`.
 *
 * So: classify by class where a class exists, fall back to message and code,
 * and never assume the value is an Error. This function must not throw — every
 * `catch` in the payment hook routes through it, so an exception raised here
 * would escape as an unhandled rejection in the middle of signing.
 *
 * This mirrors the EVM side's `humanizeTxError.ts` in intent. It is deliberately
 * NOT shared with it: that module classifies viem/EIP-1193 errors by regex over
 * nested `cause` chains, which is the right shape there and the wrong one here,
 * where real classes are available and authoritative.
 */

import {
  WalletConnectionError,
  WalletDisconnectedError,
  WalletDisconnectionError,
  WalletGetNetworkError,
  WalletNotFoundError,
  WalletNotSelectedError,
  WalletSignMessageError,
  WalletSignTransactionError,
  WalletSignTypedDataError,
  WalletSwitchChainError,
  WalletWindowClosedError,
} from '@tronweb3/tronwallet-abstract-adapter'

/**
 * What the checkout does about it. Each kind maps to one user-facing state
 * with its own copy and its own remedy — there is no generic "it failed".
 */
export type TronErrorKind =
  | 'user_rejected'
  | 'wallet_not_found'
  | 'wallet_disconnected'
  | 'wrong_network'
  | 'connection_failed'
  | 'sign_failed'
  | 'network_error'
  | 'unknown'

export interface TronCheckoutError {
  kind: TronErrorKind
  /** Bounded, single-line, safe to render. Never the whole stack. */
  detail: string
}

/** EIP-1193 / TIP-1193: the payer declined in their wallet. */
const USER_REJECTED_CODE = 4001

const USER_REJECT_RE =
  /user rejected|user denied|user cancel|denied (the )?(transaction|request|signature)|rejected the request|cancell?ed by user/i

/**
 * Matches the base adapter's bare-string switch-chain rejection, plus the
 * phrasings wallets use when they will not operate on the requested chain.
 */
const WRONG_NETWORK_RE =
  /switch chain|switch network|wrong network|unsupported chain|unsupported network|chain mismatch|not support.{0,20}chain/i

/**
 * "We could not reach the node", as opposed to "the node answered and the
 * answer was no". Only the former invites a retry.
 */
const TRANSIENT_RE =
  /timeout|timed out|network error|fetch failed|failed to fetch|load failed|request failed|status:\s*(408|425|429|50\d)|econnrefused|econnreset|enotfound|socket hang up|connection (refused|reset|closed)|service unavailable|bad gateway|gateway timeout/i

/**
 * An answer from the chain, however it is phrased. TRON's failure receipts
 * (`REVERT`, `OUT_OF_ENERGY`, `OUT_OF_TIME`) are answers: retrying one without
 * changing anything reproduces it exactly, so they must never be classified as
 * transport faults.
 */
const CHAIN_ANSWER_RE =
  /revert|out_of_energy|out_of_time|out of energy|bandwidth|insufficient balance|validate error|contract_validate/i

/**
 * Read a message off an arbitrary rejection value without trusting it.
 *
 * Everything here is guarded because the input is genuinely arbitrary: a Proxy
 * whose `get` trap throws, an object with a throwing `message` getter, a
 * null-prototype object, a Symbol. Returning "" is always safe — the classifier
 * simply falls through to `unknown`.
 */
function rawMessage(err: unknown): string {
  try {
    if (typeof err === 'string') return err
    if (err instanceof Error) return typeof err.message === 'string' ? err.message : ''
    if (err !== null && typeof err === 'object') {
      const message = (err as { message?: unknown }).message
      if (typeof message === 'string') return message
    }
  } catch {
    // A hostile getter or proxy trap. Nothing to read; carry on.
  }
  return ''
}

/** The `code` off a POJO rejection, when there is one. Same guarantees. */
function rawCode(err: unknown): unknown {
  try {
    if (err !== null && typeof err === 'object') {
      return (err as { code?: unknown }).code
    }
  } catch {
    // Same as above.
  }
  return undefined
}

/**
 * Collapse to one bounded line. The checkout renders this next to its own copy,
 * so it must not be a stack trace and must not break the layout — the same
 * treatment `usePaymentIntent` gives a backend error detail.
 */
function toDetail(message: string): string {
  const firstLine = message.split('\n')[0]!.trim()
  return firstLine.length > 160 ? `${firstLine.slice(0, 159)}…` : firstLine
}

export function toCheckoutError(err: unknown): TronCheckoutError {
  const message = rawMessage(err)
  const detail = toDetail(message)

  // The payer declining is checked first and across every shape, because it is
  // the one outcome that is not a fault at all. It arrives as a typed class
  // wrapping the wallet's own text, as a 4001, or as a bare message.
  if (USER_REJECT_RE.test(message) || rawCode(err) === USER_REJECTED_CODE) {
    return { kind: 'user_rejected', detail }
  }

  // Chain trouble before the generic classes: `WalletGetNetworkError` means we
  // could not establish which chain the wallet is on, and the checkout must
  // fail closed there rather than let a payment proceed unverified.
  if (
    err instanceof WalletSwitchChainError ||
    err instanceof WalletGetNetworkError ||
    WRONG_NETWORK_RE.test(message)
  ) {
    return { kind: 'wrong_network', detail }
  }

  if (err instanceof WalletNotFoundError) {
    return { kind: 'wallet_not_found', detail }
  }

  if (
    err instanceof WalletDisconnectedError ||
    err instanceof WalletDisconnectionError
  ) {
    return { kind: 'wallet_disconnected', detail }
  }

  if (
    err instanceof WalletConnectionError ||
    err instanceof WalletWindowClosedError ||
    err instanceof WalletNotSelectedError
  ) {
    return { kind: 'connection_failed', detail }
  }

  if (
    err instanceof WalletSignTransactionError ||
    err instanceof WalletSignMessageError ||
    err instanceof WalletSignTypedDataError
  ) {
    return { kind: 'sign_failed', detail }
  }

  // Transport faults last among the classified kinds, and never when the text
  // carries an answer from the chain.
  if (!CHAIN_ANSWER_RE.test(message) && TRANSIENT_RE.test(message)) {
    return { kind: 'network_error', detail }
  }

  return { kind: 'unknown', detail }
}
