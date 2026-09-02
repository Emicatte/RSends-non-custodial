/**
 * One normaliser stands between the wallet adapters and the checkout state
 * machine, and these are the shapes it has to survive.
 *
 * The TRON adapters do not throw one kind of thing. They throw typed
 * `WalletError` subclasses on most paths, but the base `Adapter.switchChain`
 * does `Promise.reject("The current wallet doesn't support switch chain.")` —
 * a BARE STRING, not an Error. That is not a hypothetical: it is exactly what
 * the WalletConnect path rejects with, because WalletConnectAdapter never
 * overrides switchChain. Any `err.message` read would be `undefined` there and
 * a `err instanceof Error` branch would fall through, so the one path the
 * normaliser exists to describe is the one a naive implementation crashes on.
 */
import {
  WalletConnectionError,
  WalletDisconnectedError,
  WalletNotFoundError,
  WalletSignTransactionError,
  WalletSwitchChainError,
} from '@tronweb3/tronwallet-abstract-adapter'

import { toCheckoutError } from '@/lib/web3/tron/tronErrors'

describe('typed WalletError subclasses are classified by class', () => {
  it('a rejected signature is the payer cancelling, not a failure', () => {
    // Recoverable: the payer stays on the page and Pay is offered again.
    expect(
      toCheckoutError(
        new WalletSignTransactionError('User rejected the request.'),
      ).kind,
    ).toBe('user_rejected')
  })

  it('a signature that failed for any other reason is sign_failed', () => {
    // Same class, opposite remedy — so the message, not just the class,
    // decides. Retrying is honest here; claiming the payer cancelled is not.
    expect(
      toCheckoutError(new WalletSignTransactionError('Internal JSON-RPC error'))
        .kind,
    ).toBe('sign_failed')
  })

  it('a disconnect mid-flow is its own state', () => {
    expect(toCheckoutError(new WalletDisconnectedError()).kind).toBe(
      'wallet_disconnected',
    )
  })

  it('a missing wallet is not a failed payment', () => {
    expect(toCheckoutError(new WalletNotFoundError()).kind).toBe(
      'wallet_not_found',
    )
  })

  it('a failed connection is not a failed payment either', () => {
    expect(toCheckoutError(new WalletConnectionError()).kind).toBe(
      'connection_failed',
    )
  })

  it('a switch-chain failure is wrong_network', () => {
    expect(toCheckoutError(new WalletSwitchChainError()).kind).toBe(
      'wrong_network',
    )
  })
})

describe('untyped rejections do not crash the checkout', () => {
  it('classifies the bare string the WalletConnect switchChain path rejects with', () => {
    // The literal value from the base Adapter. This is the assertion the whole
    // module is here for.
    const kind = toCheckoutError(
      "The current wallet doesn't support switch chain.",
    ).kind
    expect(kind).toBe('wrong_network')
  })

  it('reads a plain object carrying code and message', () => {
    // Injected providers reject with POJOs that are not Errors at all.
    expect(toCheckoutError({ code: -32002, message: 'Already processing' }).kind)
      .toBe('unknown')
    expect(
      toCheckoutError({ code: 4001, message: 'User denied transaction' }).kind,
    ).toBe('user_rejected')
  })

  it('survives undefined, null and shapes carrying nothing useful', () => {
    for (const value of [undefined, null, {}, [], 0, false, NaN]) {
      const result = toCheckoutError(value)
      expect(result.kind).toBe('unknown')
      expect(typeof result.detail).toBe('string')
    }
  })

  it('never throws, whatever it is handed', () => {
    // A normaliser that can throw defeats its own purpose: every catch in the
    // payment hook routes through it, so an exception here would escape as an
    // unhandled rejection during signing.
    const hostile = [
      Symbol('nope'),
      () => undefined,
      new Proxy({}, { get() { throw new Error('trap') } }),
      Object.create(null),
      { get message() { throw new Error('getter blew up') } },
    ]
    for (const value of hostile) {
      expect(() => toCheckoutError(value)).not.toThrow()
    }
  })
})

describe('transport faults are told apart from answers', () => {
  it('a network failure invites a retry', () => {
    expect(toCheckoutError(new Error('fetch failed')).kind).toBe('network_error')
    expect(toCheckoutError(new Error('Request failed. Status: 503')).kind).toBe(
      'network_error',
    )
  })

  it('an out-of-energy answer is not a transport fault', () => {
    // The chain answered. Calling this transient would invite a retry that is
    // guaranteed to fail the same way.
    expect(toCheckoutError(new Error('OUT_OF_ENERGY')).kind).not.toBe(
      'network_error',
    )
  })
})

describe('detail is safe to render', () => {
  it('is bounded and single-line', () => {
    const result = toCheckoutError(new Error('x'.repeat(5_000) + '\nsecond line'))
    expect(result.detail.length).toBeLessThanOrEqual(160)
    expect(result.detail).not.toContain('\n')
  })
})
