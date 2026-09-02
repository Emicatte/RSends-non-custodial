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

import {
  TronBroadcastError,
  decodeTronMessage,
  toCheckoutError,
} from '@/lib/web3/tron/tronErrors'

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

describe('node refusals are classified by code, and the hex decoded once', () => {
  const hex = (s: string) => Buffer.from(s, 'utf8').toString('hex')

  it('the hex message is decoded exactly once', () => {
    // TRON returns error text hex-encoded. Decoding lives here and nowhere
    // else, so there is one place that knows that.
    const raw = hex('contract validate error')
    expect(decodeTronMessage(raw)).toBe('contract validate error')

    const result = toCheckoutError(
      new TronBroadcastError('CONTRACT_VALIDATE_ERROR', raw),
    )
    expect(result.detail).toContain('contract validate error')
    // Not double-decoded, and the raw hex never reaches the payer.
    expect(result.detail).not.toContain(raw)
  })

  it('leaves text alone when it is not hex', () => {
    // Some nodes answer in plain text. Re-decoding that would mangle it.
    expect(decodeTronMessage('already exists')).toBe('already exists')
    expect(decodeTronMessage('')).toBe('')
    // Odd length is not decodable hex.
    expect(decodeTronMessage('abc')).toBe('abc')
  })

  it('keeps the raw value when the decode is not plausibly text', () => {
    // Hex-shaped but binary: showing mojibake would be worse than the hex.
    expect(decodeTronMessage('00010203')).toBe('00010203')
  })

  it('routes both staleness codes to the recoverable kind', () => {
    for (const code of ['TRANSACTION_EXPIRATION_ERROR', 'TAPOS_ERROR']) {
      expect(toCheckoutError(new TronBroadcastError(code, hex('stale'))).kind).toBe(
        'tx_expired',
      )
    }
  })

  it('routes every other code to broadcast_failed', () => {
    for (const code of ['SIGERROR', 'CONTRACT_VALIDATE_ERROR', 'BANDWITH_ERROR']) {
      expect(toCheckoutError(new TronBroadcastError(code, hex('no'))).kind).toBe(
        'broadcast_failed',
      )
    }
  })
})

describe('detail is safe to render', () => {
  it('is bounded and single-line', () => {
    const result = toCheckoutError(new Error('x'.repeat(5_000) + '\nsecond line'))
    expect(result.detail.length).toBeLessThanOrEqual(160)
    expect(result.detail).not.toContain('\n')
  })
})
