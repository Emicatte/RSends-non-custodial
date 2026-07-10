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
