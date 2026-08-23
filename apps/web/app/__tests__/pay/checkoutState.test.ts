/**
 * lib/web3/checkoutState — the pure state deriver at the heart of the hosted
 * checkout. Every step of the target machine is reachable from an explicit
 * input fixture; precedence and the two structural invariants are pinned:
 *   1. the permit path can never yield an approve state,
 *   2. allowance >= total skips the approve step entirely.
 * Terminal intent statuses (expired / already paid / not found) are handled
 * upstream at page level — this deriver never runs for them.
 */
import {
  deriveCheckoutStep,
  type CheckoutInputs,
} from '@/lib/web3/checkoutState'

/** A connected, funded, permit-token session ready to pay. */
function inputs(overrides: Partial<CheckoutInputs> = {}): CheckoutInputs {
  return {
    isConnected: true,
    onCorrectChain: true,
    usesPermit: true,
    isNative: false,
    fee: 600_000n,
    total: 50_600_000n,
    balance: 100_000_000n,
    allowance: null,
    permitReady: true,
    approvePromptOpen: false,
    approveHash: null,
    approveConfirmed: false,
    payPromptOpen: false,
    payHash: null,
    payMined: false,
    payReverted: false,
    sendFailed: false,
    sendFailedTransient: false,
    chainUnreachable: false,
    receiptUnreadable: false,
    userRejected: false,
    backendPaid: false,
    ...overrides,
  }
}

describe('connection and network', () => {
  it('connect when the wallet is not connected', () => {
    expect(deriveCheckoutStep(inputs({ isConnected: false }))).toBe('connect')
  })

  it('wrong_network when connected on another chain (recoverable)', () => {
    expect(deriveCheckoutStep(inputs({ onCorrectChain: false }))).toBe(
      'wrong_network',
    )
    // ...and back to ready once switched.
    expect(deriveCheckoutStep(inputs())).toBe('ready')
  })
})

describe('quoting and balance', () => {
  it('quoting while the fee is unknown', () => {
    expect(deriveCheckoutStep(inputs({ fee: null, total: null }))).toBe(
      'quoting',
    )
  })

  it('quoting while permit prerequisites are loading', () => {
    expect(deriveCheckoutStep(inputs({ permitReady: false }))).toBe('quoting')
  })

  it('insufficient_balance when the balance cannot cover the total', () => {
    expect(deriveCheckoutStep(inputs({ balance: 50_000_000n }))).toBe(
      'insufficient_balance',
    )
  })

  it('recovers to ready when the balance becomes sufficient (recheck)', () => {
    expect(deriveCheckoutStep(inputs({ balance: 50_600_000n }))).toBe('ready')
  })

  it('unknown balance does not block (no false negatives)', () => {
    expect(deriveCheckoutStep(inputs({ balance: null }))).toBe('ready')
  })
})

describe('approve+pay fallback path', () => {
  const fallback = { usesPermit: false, allowance: 0n }

  it('needs_approve when the allowance is below the total', () => {
    expect(deriveCheckoutStep(inputs(fallback))).toBe('needs_approve')
  })

  it('skips approve entirely when the allowance covers the total', () => {
    expect(
      deriveCheckoutStep(inputs({ ...fallback, allowance: 50_600_000n })),
    ).toBe('ready')
    expect(
      deriveCheckoutStep(inputs({ ...fallback, allowance: 99_999_999_999n })),
    ).toBe('ready')
  })

  it('approving while the wallet prompt is open', () => {
    expect(
      deriveCheckoutStep(inputs({ ...fallback, approvePromptOpen: true })),
    ).toBe('approving')
  })

  it('approve_pending while the approve tx is on-chain', () => {
    expect(
      deriveCheckoutStep(inputs({ ...fallback, approveHash: '0xa1' })),
    ).toBe('approve_pending')
  })

  it('ready_to_pay once the approve tx confirmed', () => {
    expect(
      deriveCheckoutStep(
        inputs({
          ...fallback,
          allowance: 50_600_000n,
          approveHash: '0xa1',
          approveConfirmed: true,
        }),
      ),
    ).toBe('ready_to_pay')
  })

  it('INVARIANT: the permit path never yields an approve state', () => {
    // Even with a zero allowance, a permit token goes straight to ready.
    expect(deriveCheckoutStep(inputs({ allowance: 0n }))).toBe('ready')
  })

  it('native payments never need approve', () => {
    expect(
      deriveCheckoutStep(
        inputs({ usesPermit: false, isNative: true, allowance: null }),
      ),
    ).toBe('ready')
  })
})

describe('payment execution', () => {
  it('paying while the wallet prompt (or permit signature) is open', () => {
    expect(deriveCheckoutStep(inputs({ payPromptOpen: true }))).toBe('paying')
  })

  it('tx_pending once the pay tx is sent', () => {
    expect(deriveCheckoutStep(inputs({ payHash: '0xdead' }))).toBe('tx_pending')
  })

  it('syncing when mined but the backend has not caught up', () => {
    expect(
      deriveCheckoutStep(inputs({ payHash: '0xdead', payMined: true })),
    ).toBe('syncing')
  })

  it('success once mined AND the backend reflects the payment', () => {
    expect(
      deriveCheckoutStep(
        inputs({ payHash: '0xdead', payMined: true, backendPaid: true }),
      ),
    ).toBe('success')
  })
})

describe('rejected and failed', () => {
  it('rejected when the payer cancels a wallet prompt (recoverable)', () => {
    expect(deriveCheckoutStep(inputs({ userRejected: true }))).toBe('rejected')
  })

  it('failed when the pay tx reverted', () => {
    expect(
      deriveCheckoutStep(
        inputs({ payHash: '0xdead', payMined: true, payReverted: true }),
      ),
    ).toBe('failed')
  })

  it('failed when the send itself errored', () => {
    expect(deriveCheckoutStep(inputs({ sendFailed: true }))).toBe('failed')
  })

  it('failure wins over rejection bookkeeping', () => {
    expect(
      deriveCheckoutStep(inputs({ sendFailed: true, userRejected: false })),
    ).toBe('failed')
  })

  it('recovery: clearing the flags returns to the prior actionable state', () => {
    // permit path → ready
    expect(deriveCheckoutStep(inputs())).toBe('ready')
    // fallback path pre-approve → needs_approve
    expect(
      deriveCheckoutStep(inputs({ usesPermit: false, allowance: 0n })),
    ).toBe('needs_approve')
    // fallback path post-approve → ready_to_pay
    expect(
      deriveCheckoutStep(
        inputs({
          usesPermit: false,
          allowance: 50_600_000n,
          approveHash: '0xa1',
          approveConfirmed: true,
        }),
      ),
    ).toBe('ready_to_pay')
  })
})

describe('precedence', () => {
  it('terminal payment outcome outranks connection state', () => {
    // Wallet disconnected AFTER paying must not hide the outcome.
    expect(
      deriveCheckoutStep(
        inputs({
          isConnected: false,
          payHash: '0xdead',
          payMined: true,
          backendPaid: true,
        }),
      ),
    ).toBe('success')
  })

  it('tx_pending outranks wrong_network (switching later must not lose the tx)', () => {
    expect(
      deriveCheckoutStep(inputs({ onCorrectChain: false, payHash: '0xdead' })),
    ).toBe('tx_pending')
  })

  it('connect outranks quoting and balance states', () => {
    expect(
      deriveCheckoutStep(inputs({ isConnected: false, fee: null, total: null })),
    ).toBe('connect')
  })

  it('wrong_network outranks insufficient_balance (balance read is chain-scoped)', () => {
    expect(
      deriveCheckoutStep(inputs({ onCorrectChain: false, balance: 0n })),
    ).toBe('wrong_network')
  })
})

// ── Network failure: transient vs terminal ───────────────────────
//
// The 2026-08-22 outage: the chain could not be read at all. Every read
// returned undefined, which the deriver could not tell apart from "still
// loading", so the page sat on `quoting` forever with nothing to pay.
//
// The two rules that matter to a payer:
//   - a payment that was SENT but cannot be read is UNKNOWN, never failed;
//   - a network fault invites a retry, a revert does not.

describe('chain unreachable (no transaction exists)', () => {
  it('chain_unreachable when the reads that build the tx cannot be made', () => {
    expect(
      deriveCheckoutStep(inputs({ chainUnreachable: true, fee: null, total: null })),
    ).toBe('chain_unreachable')
  })

  it('chain_unreachable when the send itself failed for a network reason', () => {
    expect(deriveCheckoutStep(inputs({ sendFailedTransient: true }))).toBe(
      'chain_unreachable',
    )
  })

  it('never reports quoting while the chain is unreadable', () => {
    // The bug of record: a failing quoteFee read is indistinguishable from a
    // pending one, so the payer waited on a spinner that would never resolve.
    expect(
      deriveCheckoutStep(inputs({ chainUnreachable: true, fee: null, total: null })),
    ).not.toBe('quoting')
  })

  it('connect and wrong_network still outrank it (fix the session first)', () => {
    expect(
      deriveCheckoutStep(inputs({ chainUnreachable: true, isConnected: false })),
    ).toBe('connect')
    expect(
      deriveCheckoutStep(inputs({ chainUnreachable: true, onCorrectChain: false })),
    ).toBe('wrong_network')
  })

  it('a payer rejection stays distinct from a network failure', () => {
    expect(deriveCheckoutStep(inputs({ userRejected: true }))).toBe('rejected')
    expect(
      deriveCheckoutStep(inputs({ userRejected: true, chainUnreachable: true })),
    ).toBe('rejected')
  })
})

describe('confirmation unknown (a transaction was sent)', () => {
  it('confirmation_unknown when the receipt cannot be read', () => {
    expect(
      deriveCheckoutStep(inputs({ payHash: '0xdead', receiptUnreadable: true })),
    ).toBe('confirmation_unknown')
  })

  it('NEVER reports failed when the tx was sent and the chain is unreadable', () => {
    // Telling a payer their money is gone when it is not is the worst
    // possible error in this product.
    const step = deriveCheckoutStep(
      inputs({
        payHash: '0xdead',
        receiptUnreadable: true,
        chainUnreachable: true,
        sendFailedTransient: true,
      }),
    )
    expect(step).not.toBe('failed')
    expect(step).toBe('confirmation_unknown')
  })

  it('an unreadable receipt outranks tx_pending (a spinner is not an answer)', () => {
    expect(deriveCheckoutStep(inputs({ payHash: '0xdead' }))).toBe('tx_pending')
    expect(
      deriveCheckoutStep(inputs({ payHash: '0xdead', receiptUnreadable: true })),
    ).toBe('confirmation_unknown')
  })

  it('a real outcome still wins: mined and reverted are never "unknown"', () => {
    expect(
      deriveCheckoutStep(
        inputs({ payHash: '0xdead', payMined: true, receiptUnreadable: true, backendPaid: true }),
      ),
    ).toBe('success')
    expect(
      deriveCheckoutStep(
        inputs({ payHash: '0xdead', payReverted: true, receiptUnreadable: true }),
      ),
    ).toBe('failed')
  })
})

describe('terminal failure stays terminal', () => {
  it('a reverted transaction is failed, not transient', () => {
    expect(deriveCheckoutStep(inputs({ payReverted: true }))).toBe('failed')
  })

  it('a non-network send error is failed', () => {
    expect(deriveCheckoutStep(inputs({ sendFailed: true }))).toBe('failed')
  })

  it('a transient send error outranks the terminal classification', () => {
    // Both flags set = classified transient; the transient branch must win,
    // or a network blip reads as "your transaction did not complete".
    expect(
      deriveCheckoutStep(inputs({ sendFailed: true, sendFailedTransient: true })),
    ).toBe('chain_unreachable')
  })
})
