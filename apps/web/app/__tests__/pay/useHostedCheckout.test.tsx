/**
 * lib/web3/useHostedCheckout — the central hook owning the wallet flow.
 * wagmi is mocked wholesale (shared factory in test-utils/wagmiMock — the
 * real ESM package never loads); RainbowKit is never imported by the hook.
 * Walks the full journeys: connect → wrong network → switch → quoting →
 * ready; insufficient balance and recovery; the approve+pay fallback with
 * exact approve args; the permit path with exact typed data and
 * payWithPermit args; native payNative with value = total; user-reject and
 * failure recovery via retry(); mined → syncing → success.
 */
import { act, renderHook } from '@testing-library/react'
import { zeroAddress } from 'viem'

jest.mock('wagmi', () => {
  const m = require('@/test-utils/wagmiMock')
  return m.wagmiModuleMock(m.wagmiState)
})

import { resetWagmiState, wagmiState as mockWagmi } from '@/test-utils/wagmiMock'
import { useHostedCheckout } from '@/lib/web3/useHostedCheckout'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'

const ROUTER = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA' as const
const TOKEN = '0x036CbD53842c5426634e7929541eC2318f3dCF7e' as const
const PAYER = '0x1111111111111111111111111111111111111111' as const
const INVOICE = ('0x' + 'ab'.repeat(32)) as `0x${string}`

function intent(overrides: Partial<OnChainIntent> = {}): OnChainIntent {
  return {
    invoiceId: INVOICE,
    merchant: ROUTER,
    token: TOKEN,
    amount: 50_000_000n,
    fee: 600_000n,
    decimals: 6,
    chainId: 84532,
    router: ROUTER,
    routerVersion: 1,
    permitType: 'eip2612',
    permitVersion: '2',
    ...overrides,
  }
}

function fresh(overrides: Partial<import('@/test-utils/wagmiMock').WagmiState> = {}) {
  resetWagmiState(overrides)
  // Funded permit-ready defaults; individual tests override.
  mockWagmi.reads = {
    balanceOf: 100_000_000n,
    nonces: 7n,
    name: 'USDC',
    ...((overrides.reads as Record<string, unknown>) ?? {}),
  }
}

const deps = { backendPaid: false, onMined: jest.fn() }

function render(oc: OnChainIntent, d = deps) {
  return renderHook(({ backendPaid }) => useHostedCheckout(oc, { ...d, backendPaid }), {
    initialProps: { backendPaid: d.backendPaid },
  })
}

beforeEach(() => {
  deps.onMined = jest.fn()
})

describe('session prerequisites', () => {
  it('connect → wrong_network → switch → ready', () => {
    fresh({ isConnected: false, address: undefined })
    const { result, rerender } = render(intent())
    expect(result.current.step).toBe('connect')

    Object.assign(mockWagmi, { isConnected: true, address: PAYER, chainId: 1 })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wrong_network')

    act(() => result.current.switchNetwork())
    expect(mockWagmi.switchChain).toHaveBeenCalledWith({ chainId: 84532 })

    mockWagmi.chainId = 84532
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })

  it('quoting while the on-chain quoteFee fallback is loading, then ready', () => {
    fresh()
    const { result, rerender } = render(intent({ fee: null }))
    expect(result.current.step).toBe('quoting')
    expect(result.current.fee).toBeNull()

    mockWagmi.reads.quoteFee = 600_000n
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
    expect(result.current.fee).toBe(600_000n)
    expect(result.current.total).toBe(50_600_000n)
  })

  it('insufficient_balance rechecks on balance change', () => {
    fresh({ reads: { balanceOf: 10_000_000n } })
    const { result, rerender } = render(intent())
    expect(result.current.step).toBe('insufficient_balance')

    mockWagmi.reads.balanceOf = 60_000_000n
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })
})

describe('approve+pay fallback path', () => {
  const fallbackIntent = () => intent({ permitType: 'none' })

  it('walks needs_approve → approving → approve_pending → ready_to_pay with exact args', () => {
    fresh({ reads: { balanceOf: 100_000_000n, allowance: 0n } })
    const { result, rerender } = render(fallbackIntent())
    expect(result.current.step).toBe('needs_approve')

    act(() => result.current.approve())
    expect(mockWagmi.approveWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: TOKEN,
        functionName: 'approve',
        args: [ROUTER, 50_600_000n], // exactly amount + fee, never infinite
        chainId: 84532,
      }),
    )

    mockWagmi.approveWrite.isPending = true
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('approving')

    mockWagmi.approveWrite.isPending = false
    mockWagmi.approveWrite.data = '0xaaa1'
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('approve_pending')

    mockWagmi.receipts['0xaaa1'] = { status: 'success' }
    mockWagmi.reads.allowance = 50_600_000n
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready_to_pay')
    expect(mockWagmi.refetch.allowance).toHaveBeenCalled()

    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: ROUTER,
        functionName: 'pay',
        args: [INVOICE, ROUTER, TOKEN, 50_000_000n, 600_000n],
        chainId: 84532,
      }),
    )
  })

  it('skips approve entirely when the allowance already covers the total', () => {
    fresh({ reads: { balanceOf: 100_000_000n, allowance: 50_600_000n } })
    const { result } = render(fallbackIntent())
    expect(result.current.step).toBe('ready')
  })
})

describe('permit path', () => {
  it('signs the exact typed data and calls payWithPermit', async () => {
    fresh()
    const account = (await import('viem/accounts')).privateKeyToAccount(
      '0x0123456789012345678901234567890123456789012345678901234567890123',
    )
    Object.assign(mockWagmi, { address: account.address })
    let captured: unknown
    mockWagmi.signTypedDataAsync.mockImplementation(async (typed: never) => {
      captured = typed
      return account.signTypedData(typed)
    })

    const { result } = render(intent())
    expect(result.current.step).toBe('ready')

    await act(async () => {
      await result.current.pay()
    })

    expect(captured).toMatchObject({
      domain: {
        name: 'USDC',
        version: '2',
        chainId: 84532,
        verifyingContract: TOKEN,
      },
      primaryType: 'Permit',
      message: expect.objectContaining({
        owner: account.address,
        spender: ROUTER,
        value: 50_600_000n, // permit covers amount + fee
        nonce: 7n,
      }),
    })

    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: ROUTER,
        functionName: 'payWithPermit',
        chainId: 84532,
      }),
    )
    const args = mockWagmi.payWrite.writeContract.mock.calls[0][0].args
    expect(args.slice(0, 5)).toEqual([INVOICE, ROUTER, TOKEN, 50_000_000n, 600_000n])
    expect(args[6] === 27 || args[6] === 28).toBe(true) // v
  })

  it('never surfaces an approve step even with zero allowance', () => {
    fresh({ reads: { balanceOf: 100_000_000n, nonces: 7n, name: 'USDC', allowance: 0n } })
    const { result } = render(intent())
    expect(result.current.step).toBe('ready')
  })
})

describe('native path', () => {
  it('pays with payNative and value = total', () => {
    fresh({ nativeBalance: { value: 10n ** 18n } })
    const oc = intent({
      token: zeroAddress,
      permitType: 'none',
      decimals: 18,
      amount: 10n ** 16n,
      fee: 0n,
    })
    const { result } = render(oc)
    expect(result.current.step).toBe('ready')

    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        functionName: 'payNative',
        args: [INVOICE, ROUTER, 10n ** 16n, 0n],
        value: 10n ** 16n,
        chainId: 84532,
      }),
    )
  })
})

describe('RSendsRouterV2 (fee-less, ownerless) — version-aware args', () => {
  const v2Intent = (overrides: Partial<OnChainIntent> = {}) =>
    intent({ routerVersion: 2, fee: 0n, ...overrides })

  it('v2 fallback path: approve exactly amount, then 4-arg pay (no maxFee)', () => {
    fresh({ reads: { balanceOf: 100_000_000n, allowance: 0n } })
    const { result, rerender } = render(v2Intent({ permitType: 'none' }))
    expect(result.current.step).toBe('needs_approve')
    expect(result.current.fee).toBe(0n)
    expect(result.current.total).toBe(50_000_000n) // total == amount, no fee term

    act(() => result.current.approve())
    expect(mockWagmi.approveWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: TOKEN,
        functionName: 'approve',
        args: [ROUTER, 50_000_000n], // exactly amount — no fee in the flow
        chainId: 84532,
      }),
    )

    mockWagmi.reads.allowance = 50_000_000n
    rerender({ backendPaid: false })
    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: ROUTER,
        functionName: 'pay',
        args: [INVOICE, ROUTER, TOKEN, 50_000_000n], // 4 args — no maxFee word
        chainId: 84532,
      }),
    )
  })

  it('v2 permit path: signs value == exactly amount, 8-arg payWithPermit', async () => {
    fresh()
    const account = (await import('viem/accounts')).privateKeyToAccount(
      '0x0123456789012345678901234567890123456789012345678901234567890123',
    )
    Object.assign(mockWagmi, { address: account.address })
    let captured: unknown
    mockWagmi.signTypedDataAsync.mockImplementation(async (typed: never) => {
      captured = typed
      return account.signTypedData(typed)
    })

    const { result } = render(v2Intent())
    expect(result.current.step).toBe('ready')

    await act(async () => {
      await result.current.pay()
    })

    expect(captured).toMatchObject({
      primaryType: 'Permit',
      message: expect.objectContaining({
        spender: ROUTER,
        value: 50_000_000n, // permit covers exactly amount — no fee term
      }),
    })

    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: ROUTER,
        functionName: 'payWithPermit',
        chainId: 84532,
      }),
    )
    const args = mockWagmi.payWrite.writeContract.mock.calls[0][0].args
    expect(args).toHaveLength(8) // no maxFee: invoiceId, merchant, token, amount, deadline, v, r, s
    expect(args.slice(0, 4)).toEqual([INVOICE, ROUTER, TOKEN, 50_000_000n])
    expect(args[5] === 27 || args[5] === 28).toBe(true) // v directly after deadline
  })

  it('v2 native path: 3-arg payNative with value == exactly amount', () => {
    fresh({ nativeBalance: { value: 10n ** 18n } })
    const oc = v2Intent({
      token: zeroAddress,
      permitType: 'none',
      decimals: 18,
      amount: 10n ** 16n,
    })
    const { result } = render(oc)
    expect(result.current.step).toBe('ready')

    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        functionName: 'payNative',
        args: [INVOICE, ROUTER, 10n ** 16n], // 3 args — no maxFee
        value: 10n ** 16n,
        chainId: 84532,
      }),
    )
  })

  it('v2 never quotes: fee is structurally 0 even on a malformed fee:null payload', () => {
    fresh()
    const { result } = render(v2Intent({ fee: null }))
    // No quoteFee exists on v2 — the hook must not hang in `quoting`.
    expect(result.current.step).toBe('ready')
    expect(result.current.fee).toBe(0n)
    expect(result.current.total).toBe(50_000_000n)
  })
})

describe('outcomes and recovery', () => {
  it('tx_pending → syncing (onMined fires once) → success', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xpay1'
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')
    expect(result.current.payHash).toBe('0xpay1')

    mockWagmi.receipts['0xpay1'] = { status: 'success' }
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('syncing')
    expect(deps.onMined).toHaveBeenCalledTimes(1)

    rerender({ backendPaid: false })
    expect(deps.onMined).toHaveBeenCalledTimes(1) // once, not per render

    rerender({ backendPaid: true })
    expect(result.current.step).toBe('success')
  })

  it('user rejection is recoverable via retry()', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.error = new Error('User rejected the request.')
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('rejected')

    act(() => result.current.retry())
    expect(mockWagmi.payWrite.reset).toHaveBeenCalled()
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })

  it('a rejected permit signature is recoverable too', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.signError = new Error('User denied message signature')
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('rejected')

    act(() => result.current.retry())
    expect(mockWagmi.signReset).toHaveBeenCalled()
  })

  it('reverted receipt → failed, with the hash still exposed', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    mockWagmi.receipts['0xdead'] = { status: 'reverted' }
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('failed')
    expect(result.current.payHash).toBe('0xdead')
  })

  it('non-rejection send errors → failed, recoverable via retry()', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.error = new Error('execution reverted: FeeTooHigh()')
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('failed')

    act(() => result.current.retry())
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })
})

// ── The chain cannot be read (outage of 2026-08-22) ──────────────
//
// Every wagmi read used to discard its `error`, so a failing read looked
// exactly like a pending one and the hook reported `quoting` forever: the
// payer got a spinner on a disabled Pay button and no explanation.

const RPC_DOWN = new Error(
  'HTTP request failed. Status: 503. Details: no backend is currently healthy to serve traffic',
)

describe('chain unreachable', () => {
  it('a failing quoteFee read reports chain_unreachable, not quoting', () => {
    fresh()
    mockWagmi.readErrors.quoteFee = RPC_DOWN
    const { result } = render(intent({ fee: null }))
    expect(result.current.step).toBe('chain_unreachable')
    expect(result.current.fee).toBeNull()
  })

  it('a failing permit prerequisite read reports chain_unreachable', () => {
    fresh()
    mockWagmi.readErrors.nonces = RPC_DOWN
    const { result } = render(intent())
    expect(result.current.step).toBe('chain_unreachable')
  })

  it('a failing allowance read reports chain_unreachable on the approve path', () => {
    fresh()
    mockWagmi.readErrors.allowance = RPC_DOWN
    const { result } = render(
      intent({ permitType: 'none', fee: 600_000n }),
    )
    expect(result.current.step).toBe('chain_unreachable')
  })

  it('a balance-only read failure does NOT block (balance never blocked)', () => {
    fresh()
    mockWagmi.readErrors.balanceOf = RPC_DOWN
    const { result } = render(intent())
    expect(result.current.step).toBe('ready')
    expect(result.current.balance).toBeNull()
  })

  it('recovers to ready when the reads start answering again', () => {
    fresh()
    mockWagmi.readErrors.quoteFee = RPC_DOWN
    const { result, rerender } = render(intent({ fee: null }))
    expect(result.current.step).toBe('chain_unreachable')

    delete mockWagmi.readErrors.quoteFee
    mockWagmi.reads.quoteFee = 600_000n
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })

  it('retryReads() refetches the chain reads (the manual control)', () => {
    fresh()
    mockWagmi.readErrors.quoteFee = RPC_DOWN
    const { result } = render(intent({ fee: null }))

    act(() => result.current.retryReads())
    expect(mockWagmi.refetch.quoteFee).toHaveBeenCalled()
  })

  it('a network send error is transient, NOT failed', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.error = RPC_DOWN
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('chain_unreachable')
    expect(result.current.step).not.toBe('failed')
  })

  it('the backend degraded path is untouched: fee null + a live chain still pays', () => {
    // feeUnavailable from the backend is NOT an outage — the client quotes
    // the fee on-chain itself and the payer proceeds.
    fresh()
    mockWagmi.reads.quoteFee = 600_000n
    const { result } = render(intent({ fee: null }))
    expect(result.current.step).toBe('ready')
    expect(result.current.fee).toBe(600_000n)
    expect(result.current.total).toBe(50_600_000n)
  })
})

describe('confirmation unknown', () => {
  it('an unreadable receipt after a sent tx is UNKNOWN, never failed', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    mockWagmi.receiptErrors['0xdead'] = RPC_DOWN
    rerender({ backendPaid: false })

    expect(result.current.step).toBe('confirmation_unknown')
    expect(result.current.step).not.toBe('failed')
    expect(result.current.payHash).toBe('0xdead')
  })

  it('resolves to success when the chain answers again', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    mockWagmi.receiptErrors['0xdead'] = RPC_DOWN
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('confirmation_unknown')

    delete mockWagmi.receiptErrors['0xdead']
    mockWagmi.receipts['0xdead'] = { status: 'success' }
    rerender({ backendPaid: true })
    expect(result.current.step).toBe('success')
  })

  it('a readable revert is still failed (unknown is not a euphemism)', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    mockWagmi.receipts['0xdead'] = { status: 'reverted' }
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('failed')
  })
})

describe('confirmation unknown by stall (no receipt error is ever raised)', () => {
  // viem's waitForTransactionReceipt retries a dead RPC indefinitely and never
  // sets `error` — measured against a blocked endpoint in a real browser,
  // ~450 retries over three minutes with the hook's error still undefined.
  // Without a clock of our own the payer would sit on "Transaction sent.
  // Waiting for the network." for the entire outage, so the elapsed time since
  // the hash appeared is the signal that actually fires.
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it('flips to confirmation_unknown once the receipt stays unresolved', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')

    act(() => {
      jest.advanceTimersByTime(44_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')

    act(() => {
      jest.advanceTimersByTime(2_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('confirmation_unknown')
    expect(result.current.payHash).toBe('0xdead')
  })

  it('a receipt that lands afterwards still wins (self-correcting)', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    act(() => {
      jest.advanceTimersByTime(46_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('confirmation_unknown')

    mockWagmi.receipts['0xdead'] = { status: 'success' }
    rerender({ backendPaid: true })
    expect(result.current.step).toBe('success')
  })

  it('never fires on a healthy chain that answers in time', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    act(() => {
      jest.advanceTimersByTime(5_000)
    })
    mockWagmi.receipts['0xdead'] = { status: 'success' }
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('syncing')

    act(() => {
      jest.advanceTimersByTime(120_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('syncing')
  })
})

// ── The wallet refuses the chain ─────────────────────────────────
//
// The bug of record: `useSwitchChain`'s error was destructured away, so a
// wallet that refuses Base Sepolia (Coinbase Smart Wallet does, in its own
// window) left the page silently repeating "switch your wallet to continue" —
// advice the wallet had already refused to take.

const CHAIN_REFUSED = new Error(
  'ChainNotConfiguredError: Chain "84532" not configured for connector "coinbaseWalletSDK".',
)

describe('wallet refuses this chain', () => {
  it('surfaces a refused switchChain instead of discarding it', () => {
    fresh({ chainId: 1 })
    const { result, rerender } = render(intent())
    expect(result.current.step).toBe('wrong_network')

    act(() => result.current.switchNetwork())
    expect(mockWagmi.switchChain).toHaveBeenCalledWith({ chainId: 84532 })

    mockWagmi.switchError = CHAIN_REFUSED
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wallet_chain_unsupported')
  })

  it('a refusal on the write path is never reported as failed', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.error = CHAIN_REFUSED
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wallet_chain_unsupported')
    expect(result.current.step).not.toBe('failed')
    expect(result.current.payHash).toBeNull()
  })

  it('a STALE switch error never pins the page once the chain is right', () => {
    fresh({ chainId: 1 })
    const { result, rerender } = render(intent())

    mockWagmi.switchError = CHAIN_REFUSED
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wallet_chain_unsupported')

    // The payer switched in the wallet itself; the old error is meaningless.
    mockWagmi.chainId = 84532
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })

  it('retry() clears the refusal (the switch mutation is reset too)', () => {
    fresh({ chainId: 1 })
    const { result, rerender } = render(intent())

    mockWagmi.switchError = CHAIN_REFUSED
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wallet_chain_unsupported')

    act(() => result.current.retry())
    expect(mockWagmi.switchReset).toHaveBeenCalled()
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('wrong_network')
  })

  it('a user rejection of the switch stays a rejection, not a wallet limitation', () => {
    fresh({ chainId: 1 })
    const { result, rerender } = render(intent())

    mockWagmi.switchError = new Error('User rejected the request.')
    rerender({ backendPaid: false })
    expect(result.current.step).not.toBe('wallet_chain_unsupported')
  })
})

// ── A wallet that has not answered yet ───────────────────────────
//
// Per production observation the prompt DOES resolve when the wallet window
// closes, so this is deliberately not a timeout: the state never changes and
// the live prompt is never reset. All that changes is what the page says
// while the payer waits, plus a non-destructive way out that is only offered
// while nothing has been broadcast.

describe('a wallet prompt that goes unanswered', () => {
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it('waitingLong flips only after the silence window, and the step never moves', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.isPending = true
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('paying')
    expect(result.current.waitingLong).toBe(false)

    act(() => {
      jest.advanceTimersByTime(19_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.waitingLong).toBe(false)

    act(() => {
      jest.advanceTimersByTime(2_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.waitingLong).toBe(true)
    // NOT a timeout: the prompt is still live and the step is unchanged.
    expect(result.current.step).toBe('paying')
    expect(mockWagmi.payWrite.reset).not.toHaveBeenCalled()
  })

  it('covers the permit signature and the approve prompt too', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.signPending = true
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('paying')
    act(() => {
      jest.advanceTimersByTime(21_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.waitingLong).toBe(true)
  })

  it('resets the moment the wallet answers', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.isPending = true
    rerender({ backendPaid: false })
    act(() => {
      jest.advanceTimersByTime(21_000)
    })
    rerender({ backendPaid: false })
    expect(result.current.waitingLong).toBe(true)

    mockWagmi.payWrite.isPending = false
    rerender({ backendPaid: false })
    expect(result.current.waitingLong).toBe(false)
  })

  it('never fires when the wallet answers promptly', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.isPending = true
    rerender({ backendPaid: false })
    act(() => {
      jest.advanceTimersByTime(3_000)
    })
    mockWagmi.payWrite.isPending = false
    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')
    expect(result.current.waitingLong).toBe(false)
  })
})

// ── Changing wallet ──────────────────────────────────────────────

describe('switching or dropping the wallet', () => {
  it('useDifferentWallet disconnects and clears the prompt state', () => {
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.isPending = true
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('paying')

    act(() => result.current.useDifferentWallet())
    expect(mockWagmi.disconnect).toHaveBeenCalled()
    expect(mockWagmi.payWrite.reset).toHaveBeenCalled()
    expect(mockWagmi.signReset).toHaveBeenCalled()

    Object.assign(mockWagmi, { isConnected: false, address: undefined })
    mockWagmi.payWrite.isPending = false
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('connect')
  })

  it('canSwitchWallet is false the moment ANY transaction exists', () => {
    fresh()
    const { result, rerender } = render(intent())
    expect(result.current.canSwitchWallet).toBe(true)

    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    expect(result.current.canSwitchWallet).toBe(false)
  })

  it('canSwitchWallet is false once an approve tx has been broadcast', () => {
    fresh({ reads: { balanceOf: 100_000_000n, allowance: 0n } })
    const { result, rerender } = render(intent({ permitType: 'none' }))
    expect(result.current.canSwitchWallet).toBe(true)

    mockWagmi.approveWrite.data = '0xaaa1'
    rerender({ backendPaid: false })
    expect(result.current.canSwitchWallet).toBe(false)
  })

  it('an IN-FLIGHT transaction survives a disconnect, hash and all', () => {
    // The money has already moved. Losing the hash would strand the payer with
    // no proof and no explorer link, which is the one thing this page must
    // never do.
    fresh()
    const { result, rerender } = render(intent())

    mockWagmi.payWrite.data = '0xdead'
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')

    Object.assign(mockWagmi, { isConnected: false, address: undefined })
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('tx_pending')
    expect(result.current.payHash).toBe('0xdead')

    mockWagmi.receipts['0xdead'] = { status: 'success' }
    rerender({ backendPaid: true })
    expect(result.current.step).toBe('success')
    expect(result.current.payHash).toBe('0xdead')
  })

  it('re-derives balance and allowance FOR the new address, keeping the intent', () => {
    // The intent is keyed by the URL, not the wallet: changing account must
    // re-read the new payer's position rather than reset the page.
    const OTHER = '0x2222222222222222222222222222222222222222' as const
    fresh({ reads: { balanceOf: 100_000_000n, allowance: 0n } })
    const { result, rerender } = render(intent({ permitType: 'none' }))
    expect(result.current.step).toBe('needs_approve')
    expect(mockWagmi.readArgs.balanceOf).toEqual([PAYER])
    expect(mockWagmi.readArgs.allowance).toEqual([PAYER, ROUTER])

    mockWagmi.address = OTHER
    mockWagmi.reads.balanceOf = 10_000_000n
    rerender({ backendPaid: false })
    // Every address-scoped read is re-issued for the new payer...
    expect(mockWagmi.readArgs.balanceOf).toEqual([OTHER])
    expect(mockWagmi.readArgs.allowance).toEqual([OTHER, ROUTER])
    // ...the intent and its total are untouched, and the new balance decides.
    expect(result.current.step).toBe('insufficient_balance')
    expect(result.current.total).toBe(50_600_000n)

    mockWagmi.reads.balanceOf = 100_000_000n
    mockWagmi.reads.allowance = 50_600_000n
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready')
  })

  it('re-derives the permit nonce for the new address (permit path)', () => {
    const OTHER = '0x2222222222222222222222222222222222222222' as const
    fresh()
    const { result, rerender } = render(intent())
    expect(mockWagmi.readArgs.nonces).toEqual([PAYER])

    mockWagmi.address = OTHER
    rerender({ backendPaid: false })
    expect(mockWagmi.readArgs.nonces).toEqual([OTHER])
    expect(result.current.step).toBe('ready')
    // The fee is address-independent by construction (quoteFee takes token +
    // amount), so it is re-derived by NOT changing — asserted, not faked.
    expect(result.current.fee).toBe(600_000n)
  })
})
