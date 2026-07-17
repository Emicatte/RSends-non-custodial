/**
 * Split checkout — the paySplit* branch of useHostedCheckout plus the split
 * block of normalizeIntent.
 *
 * The load-bearing pin: the hook builds the RSendsSplitRouter args EXACTLY
 * from the backend payload (invoiceId, token, total, recipients, sharesBps)
 * and never mutates amounts client-side — the contract recomputes the per-leg
 * amounts from total+bps, so what the payer signs IS the deterministic split.
 * The single-recipient paths are pinned untouched by useHostedCheckout.test.
 */
import { act, renderHook } from '@testing-library/react'
import { zeroAddress } from 'viem'

jest.mock('wagmi', () => {
  const m = require('@/test-utils/wagmiMock')
  return m.wagmiModuleMock(m.wagmiState)
})

import { resetWagmiState, wagmiState as mockWagmi } from '@/test-utils/wagmiMock'
import { useHostedCheckout } from '@/lib/web3/useHostedCheckout'
import {
  normalizeIntent,
  type OnChainIntent,
  type RawPaymentIntent,
} from '@/lib/web3/paymentIntent'

const SPLIT_ROUTER = '0x4444444444444444444444444444444444444444' as const
const TOKEN = '0x036CbD53842c5426634e7929541eC2318f3dCF7e' as const
const ALICE = '0x1111111111111111111111111111111111111111' as const
const BOB = '0x3333333333333333333333333333333333333333' as const
const PAYER = '0x2222222222222222222222222222222222222222' as const
const INVOICE = ('0x' + 'cd'.repeat(32)) as `0x${string}`

const TOTAL = 100_000_000n
const RECIPIENTS = [ALICE, BOB] as `0x${string}`[]
const SHARES = [7000, 3000]
const AMOUNTS = [70_000_000n, 30_000_000n]

function splitIntent(overrides: Partial<OnChainIntent> = {}): OnChainIntent {
  return {
    invoiceId: INVOICE,
    merchant: zeroAddress, // split: no single payee
    token: TOKEN,
    amount: TOTAL,
    fee: 0n, // the SplitRouter is fee-less — backend always sends "0"
    decimals: 6,
    chainId: 84532,
    router: SPLIT_ROUTER,
    permitType: 'none',
    permitVersion: '1',
    split: { recipients: RECIPIENTS, sharesBps: SHARES, amounts: AMOUNTS },
    ...overrides,
  }
}

function fresh(overrides: Partial<import('@/test-utils/wagmiMock').WagmiState> = {}) {
  resetWagmiState(overrides)
  mockWagmi.reads = {
    balanceOf: 200_000_000n,
    nonces: 7n,
    name: 'USDC',
    ...((overrides.reads as Record<string, unknown>) ?? {}),
  }
}

const deps = { backendPaid: false, onMined: jest.fn() }

function render(oc: OnChainIntent) {
  return renderHook(
    ({ backendPaid }) => useHostedCheckout(oc, { ...deps, backendPaid }),
    { initialProps: { backendPaid: false } },
  )
}

beforeEach(() => {
  deps.onMined = jest.fn()
})

describe('approve + paySplit fallback path', () => {
  it('approves exactly the total to the split router, then paySplit with the exact backend vectors', () => {
    fresh({ reads: { balanceOf: 200_000_000n, allowance: 0n } })
    const { result, rerender } = render(splitIntent())
    expect(result.current.step).toBe('needs_approve')

    act(() => result.current.approve())
    expect(mockWagmi.approveWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: TOKEN,
        functionName: 'approve',
        args: [SPLIT_ROUTER, TOTAL], // fee-less: total == amount, never infinite
        chainId: 84532,
      }),
    )

    mockWagmi.approveWrite.data = '0xsp1'
    mockWagmi.receipts['0xsp1'] = { status: 'success' }
    mockWagmi.reads.allowance = TOTAL
    rerender({ backendPaid: false })
    expect(result.current.step).toBe('ready_to_pay')

    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: SPLIT_ROUTER,
        functionName: 'paySplit',
        args: [INVOICE, TOKEN, TOTAL, RECIPIENTS, SHARES],
        chainId: 84532,
      }),
    )
  })
})

describe('permit path', () => {
  it('permit covers exactly the total and calls paySplitWithPermit with the backend vectors', async () => {
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

    const { result } = render(splitIntent({ permitType: 'eip2612', permitVersion: '2' }))
    expect(result.current.step).toBe('ready')

    await act(async () => {
      await result.current.pay()
    })

    expect(captured).toMatchObject({
      primaryType: 'Permit',
      message: expect.objectContaining({
        spender: SPLIT_ROUTER,
        value: TOTAL, // fee-less: permit covers exactly the amount
      }),
    })

    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        address: SPLIT_ROUTER,
        functionName: 'paySplitWithPermit',
        chainId: 84532,
      }),
    )
    const args = mockWagmi.payWrite.writeContract.mock.calls[0][0].args
    expect(args.slice(0, 5)).toEqual([INVOICE, TOKEN, TOTAL, RECIPIENTS, SHARES])
  })
})

describe('native path', () => {
  it('paySplitNative with value = total', () => {
    fresh({ nativeBalance: { value: 10n ** 18n } })
    const oc = splitIntent({
      token: zeroAddress,
      decimals: 18,
      amount: 10n ** 16n,
      split: {
        recipients: RECIPIENTS,
        sharesBps: SHARES,
        amounts: [7n * 10n ** 15n, 3n * 10n ** 15n],
      },
    })
    const { result } = render(oc)
    expect(result.current.step).toBe('ready')

    act(() => {
      void result.current.pay()
    })
    expect(mockWagmi.payWrite.writeContract).toHaveBeenCalledWith(
      expect.objectContaining({
        functionName: 'paySplitNative',
        args: [INVOICE, 10n ** 16n, RECIPIENTS, SHARES],
        value: 10n ** 16n,
        chainId: 84532,
      }),
    )
  })
})

describe('normalizeIntent split block', () => {
  const rawSplit = (over: Record<string, unknown> = {}): RawPaymentIntent => ({
    status: 'pending',
    expires_at: '2030-01-01T00:00:00Z',
    amount: 100,
    currency: 'USDC',
    chain: 'BASE_SEPOLIA',
    onchain: {
      invoiceId: INVOICE,
      merchant: '', // split: no single payee
      token: TOKEN,
      amount: TOTAL.toString(),
      fee: '0',
      chainId: 84532,
      router: SPLIT_ROUTER,
      function: 'paySplit',
      decimals: 6,
      isNative: false,
      permitType: 'none',
      split: {
        router: SPLIT_ROUTER,
        recipients: [ALICE, BOB],
        sharesBps: SHARES,
        amounts: AMOUNTS.map(String),
        ...((over.split as object) ?? {}),
      },
      ...over,
    },
  })

  it('parses the split vectors (empty merchant tolerated — the split IS the payee set)', () => {
    const intent = normalizeIntent(rawSplit(), 'pi_test')
    expect(intent.onchain).not.toBeNull()
    expect(intent.onchain!.split).toEqual({
      recipients: RECIPIENTS,
      sharesBps: SHARES,
      amounts: AMOUNTS,
    })
    expect(intent.onchain!.fee).toBe(0n)
    expect(intent.onchain!.router).toBe(SPLIT_ROUTER)
  })

  it('malformed split (length mismatch) → no onchain block, graceful fallback UI', () => {
    const intent = normalizeIntent(
      rawSplit({ split: { recipients: [ALICE], sharesBps: SHARES, amounts: AMOUNTS.map(String) } }),
      'pi_test',
    )
    expect(intent.onchain).toBeNull()
  })

  it('single-recipient intents keep split null', () => {
    const raw: RawPaymentIntent = {
      status: 'pending',
      expires_at: '2030-01-01T00:00:00Z',
      onchain: {
        invoiceId: INVOICE,
        merchant: PAYER,
        token: TOKEN,
        amount: '1000',
        chainId: 84532,
        router: SPLIT_ROUTER,
        decimals: 6,
      },
    }
    const intent = normalizeIntent(raw, 'pi_test')
    expect(intent.onchain).not.toBeNull()
    expect(intent.onchain!.split).toBeNull()
  })
})
