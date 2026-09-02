/**
 * The TRON payment state machine.
 *
 * The invariant every test here defends: the backend decides what "paid" means.
 * A broadcast is not proof, a transaction id is not proof, and a SUCCESS
 * receipt on chain is not proof. The receipt watch exists to explain a FAILURE
 * early — it can move a payer to failed, never to paid.
 */
import { act, renderHook, waitFor } from '@testing-library/react'

import { normalizeIntent } from '@/lib/web3/paymentIntent'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'
import type { TronWalletSession } from '@/lib/web3/tron/tronWallet'
import { useTronPayment } from '@/lib/web3/tron/useTronPayment'

const NILE = tronNetworkFor('tron_nile')!
const PAYER = 'TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb'
const MERCHANT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const TXID = 'a'.repeat(64)

const INTENT = normalizeIntent(
  {
    status: 'pending',
    chain: 'tron_nile',
    currency: 'USDT',
    amount: 10,
    amount_exact: '10.000000',
    recipient: MERCHANT,
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    onchain: null,
  },
  'pi_' + 'b'.repeat(32),
)

/** Enough energy and bandwidth staked that nothing is burned. */
const RICH = { EnergyLimit: 10 ** 7, EnergyUsed: 0, freeNetLimit: 5_000, freeNetUsed: 0 }
const PRICES = [
  { key: 'getEnergyFee', value: 210 },
  { key: 'getTransactionFee', value: 1000 },
]
/** 10 USDT, hex-encoded as a uint256 word. */
const BALANCE_10_USDT =
  '0000000000000000000000000000000000000000000000000000000000989680'

type Calls = { order: string[]; broadcast: unknown[] }

function fakeClient(over: Record<string, unknown> = {}) {
  const calls: Calls = { order: [], broadcast: [] }
  const client = {
    isAddress: (a: unknown) =>
      typeof a === 'string' && /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a),
    transactionBuilder: {
      triggerConstantContract: async (_c: string, selector: string) => {
        calls.order.push(selector === 'balanceOf(address)' ? 'balance' : 'estimate')
        if (selector === 'balanceOf(address)') {
          return {
            result: { result: true },
            constant_result: [(over.balanceWord as string) ?? BALANCE_10_USDT],
          }
        }
        return { result: { result: true }, energy_required: 31_895 }
      },
      triggerSmartContract: async () => ({
        result: { result: true },
        transaction: {
          txID: TXID,
          raw_data_hex: 'ab'.repeat(180),
          raw_data: {},
          visible: false,
        },
      }),
    },
    trx: {
      getChainParameters: async () => PRICES,
      getAccountResources: async () => (over.resources as object) ?? RICH,
      getBalance: async () => (over.balanceSun as number) ?? 10 ** 9,
      sendRawTransaction: async (signed: unknown) => {
        calls.broadcast.push(signed)
        return { result: true, txid: TXID, code: 0, message: '', transaction: signed }
      },
      getTransactionInfo: async () => (over.txInfo as object) ?? {},
    },
    ...(over.client as object),
  }
  return { client, calls }
}

function walletSession(over: Partial<TronWalletSession> = {}): TronWalletSession {
  return {
    status: 'connected',
    address: PAYER,
    kind: 'tronlink',
    chainId: NILE.chainId,
    chainReadable: true,
    wcUri: null,
    error: null,
    options: [],
    adapter: {
      signTransaction: async (tx: unknown) => ({ ...(tx as object), signature: ['sig'] }),
    } as never,
    canSwitchChain: true,
    connect: async () => {},
    disconnect: async () => {},
    switchChain: async () => {},
    clearError: () => {},
    ...over,
  }
}

function setup(opts: {
  client?: ReturnType<typeof fakeClient>
  wallet?: TronWalletSession
  intentBody?: Record<string, unknown>
  hintFails?: boolean
  backendPaid?: boolean
} = {}) {
  const client = opts.client ?? fakeClient()
  const fetches: { url: string; method: string; body?: string }[] = []

  const fetchImpl = (async (url: string, init?: RequestInit) => {
    fetches.push({
      url: String(url),
      method: init?.method ?? 'GET',
      body: init?.body as string | undefined,
    })
    if (String(url).endsWith('/tx-hint')) {
      if (opts.hintFails) throw new Error('backend route does not exist yet')
      return { ok: true, json: async () => ({}) }
    }
    return {
      ok: true,
      json: async () => ({
        status: 'pending',
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        ...opts.intentBody,
      }),
    }
  }) as unknown as typeof fetch

  const onBroadcast = jest.fn()
  const view = renderHook(
    ({ paid }: { paid: boolean }) =>
      useTronPayment(INTENT, NILE, opts.wallet ?? walletSession(), {
        backendPaid: paid,
        onBroadcast,
        getClient: (async () => client.client) as never,
        fetchImpl,
      }),
    { initialProps: { paid: opts.backendPaid ?? false } },
  )
  return { view, client, fetches, onBroadcast }
}

describe('preflight', () => {
  it('refuses_an_intent_that_is_no_longer_pending', async () => {
    const { view } = setup({ intentBody: { status: 'paid' } })
    await act(async () => void (await view.result.current.pay()))
    expect(view.result.current.status.kind).toBe('already_paid')
  })

  it('refuses_an_expired_intent', async () => {
    const { view } = setup({
      intentBody: { expires_at: new Date(Date.now() - 1000).toISOString() },
    })
    await act(async () => void (await view.result.current.pay()))
    expect(view.result.current.status.kind).toBe('expired')
  })

  it('wrong_network_on_tronlink_offers_a_switch', async () => {
    const { view, client } = setup({
      wallet: walletSession({ chainId: '0x2b6653dc', chainReadable: true }),
    })
    await act(async () => void (await view.result.current.pay()))

    const status = view.result.current.status
    expect(status).toMatchObject({ kind: 'failed', reason: 'wrong_network' })
    // Nothing was built, because nothing should be built for the wrong chain.
    expect(client.calls.order).toEqual([])
  })

  it('walletconnect_network_is_reported_as_requested_not_verified', async () => {
    // No network() on that adapter, so chainId is null and chainReadable false.
    // That is NOT a mismatch — the chain was fixed when the session was
    // requested — and it must not block the payment.
    const { view } = setup({
      wallet: walletSession({ kind: 'walletconnect', chainId: null, chainReadable: false }),
    })
    await act(async () => void (await view.result.current.pay()))
    expect(view.result.current.status.kind).toBe('processing')
  })

  it('insufficient_usdt_is_its_own_state_and_builds_nothing', async () => {
    const client = fakeClient({
      // 1 USDT against a 10 USDT invoice.
      balanceWord: '00000000000000000000000000000000000000000000000000000000000f4240',
    })
    const { view } = setup({ client })
    await act(async () => void (await view.result.current.pay()))

    expect(view.result.current.status).toMatchObject({
      kind: 'failed',
      reason: 'insufficient_usdt',
    })
    expect(client.calls.broadcast).toHaveLength(0)
  })

  it('checks_balance_before_estimating_energy', async () => {
    // Order is load-bearing: an insufficient balance makes the estimate revert,
    // and that revert read as an energy problem would tell a payer to buy TRX
    // when what they are short of is USDT.
    const client = fakeClient({
      balanceWord: '0000000000000000000000000000000000000000000000000000000000000001',
    })
    const { view } = setup({ client })
    await act(async () => void (await view.result.current.pay()))

    expect(client.calls.order[0]).toBe('balance')
    expect(client.calls.order).not.toContain('estimate')
  })

  it('insufficient_trx_is_its_own_state_and_requests_no_signature', async () => {
    let signed = false
    const client = fakeClient({ resources: {}, balanceSun: 0 })
    const wallet = walletSession({
      adapter: {
        signTransaction: async (tx: unknown) => {
          signed = true
          return { ...(tx as object), signature: ['sig'] }
        },
      } as never,
    })
    const { view } = setup({ client, wallet })
    await act(async () => void (await view.result.current.pay()))

    expect(view.result.current.status).toMatchObject({
      kind: 'failed',
      reason: 'insufficient_trx',
    })
    // The whole point: never ask for a signature on a transaction that cannot
    // execute.
    expect(signed).toBe(false)
    expect(client.calls.broadcast).toHaveLength(0)
  })

  it('treats_absent_resource_fields_as_zero', async () => {
    // TronGrid omits zero-valued fields, so a fresh account returns {}.
    const client = fakeClient({ resources: {}, balanceSun: 0 })
    const { view } = setup({ client })
    await act(async () => void (await view.result.current.pay()))

    const quote = view.result.current.quote!
    expect(quote.energyAvailable).toBe(0)
    expect(quote.bandwidthAvailable).toBe(0)
    expect(Number.isNaN(quote.costSun)).toBe(false)
    expect(quote.covered).toBe(false)
  })

  it('counts_bandwidth_shortfall_not_only_energy', async () => {
    // Plenty of energy, no bandwidth, no TRX. Pricing only energy would call
    // this free and wave it through.
    const client = fakeClient({
      resources: { EnergyLimit: 10 ** 7, EnergyUsed: 0 },
      balanceSun: 0,
    })
    const { view } = setup({ client })
    await act(async () => void (await view.result.current.pay()))

    const quote = view.result.current.quote!
    expect(quote.energyAvailable).toBeGreaterThan(quote.energyNeeded)
    expect(quote.bandwidthNeeded).toBeGreaterThan(0)
    expect(quote.costSun).toBeGreaterThan(0)
    expect(view.result.current.status).toMatchObject({ reason: 'insufficient_trx' })
  })

  it('fee_limit_is_estimate_times_margin_and_never_exceeds_the_ceiling', async () => {
    const { view } = setup()
    await act(async () => void (await view.result.current.pay()))
    // 31_895 energy x 210 sun x 1.5 = 10_046_925, under the 100 TRX ceiling.
    expect(view.result.current.quote!.feeLimit).toBe(Math.ceil(31_895 * 210 * 1.5))
    expect(view.result.current.quote!.feeLimit).toBeLessThanOrEqual(100_000_000)
  })
})

describe('signing and broadcast', () => {
  it('user_rejection_leaves_the_payer_able_to_retry', async () => {
    const wallet = walletSession({
      adapter: {
        signTransaction: async () => {
          throw new Error('User rejected the request.')
        },
      } as never,
    })
    const { view, fetches } = setup({ wallet })
    await act(async () => void (await view.result.current.pay()))

    expect(view.result.current.status).toMatchObject({
      kind: 'failed',
      reason: 'user_rejected',
    })
    // No hash to report, because nothing was sent.
    expect(fetches.filter((f) => f.url.endsWith('/tx-hint'))).toHaveLength(0)

    act(() => view.result.current.reset())
    expect(view.result.current.status.kind).toBe('idle')
  })

  it('wallet_disconnect_during_signing_is_its_own_state', async () => {
    const wallet = walletSession({
      adapter: {
        signTransaction: async () => {
          const { WalletDisconnectedError } = await import(
            '@tronweb3/tronwallet-abstract-adapter'
          )
          throw new WalletDisconnectedError()
        },
      } as never,
    })
    const { view, fetches } = setup({ wallet })
    await act(async () => void (await view.result.current.pay()))

    expect(view.result.current.status).toMatchObject({
      kind: 'failed',
      reason: 'wallet_disconnected',
    })
    expect(fetches.filter((f) => f.url.endsWith('/tx-hint'))).toHaveLength(0)
  })

  it('a bare-string rejection does not crash the state machine', async () => {
    // The shape the base adapter's switchChain rejects with. Every catch in the
    // hook routes through toCheckoutError precisely so this cannot throw.
    const wallet = walletSession({
      adapter: {
        signTransaction: async () => {
          throw "The current wallet doesn't support switch chain."
        },
      } as never,
    })
    const { view } = setup({ wallet })
    await act(async () => void (await view.result.current.pay()))
    expect(view.result.current.status).toMatchObject({
      kind: 'failed',
      reason: 'wrong_network',
    })
  })

  it('hash_is_posted_exactly_once_and_a_failed_post_changes_nothing', async () => {
    // The backend route does not exist yet; the payer must not be able to tell.
    const { view, fetches, onBroadcast } = setup({ hintFails: true })
    await act(async () => void (await view.result.current.pay()))
    await act(async () => void (await view.result.current.pay()))

    const hints = fetches.filter((f) => f.url.endsWith('/tx-hint'))
    expect(hints).toHaveLength(1)
    expect(hints[0].method).toBe('POST')
    expect(JSON.parse(hints[0].body!)).toEqual({
      tx_hash: TXID,
      payer_address: PAYER,
    })
    // Still processing, and the intent poll was still accelerated.
    expect(view.result.current.status.kind).toBe('processing')
    expect(onBroadcast).toHaveBeenCalled()
  })

  it('never sends recipient, amount or chain in the hint body', async () => {
    const { view, fetches } = setup()
    await act(async () => void (await view.result.current.pay()))
    const body = JSON.parse(
      fetches.find((f) => f.url.endsWith('/tx-hint'))!.body!,
    )
    // A hash and who sent it. Nothing a caller could use to redirect a payment.
    expect(Object.keys(body).sort()).toEqual(['payer_address', 'tx_hash'])
  })
})

describe('the receipt watch explains failure, never success', () => {
  it('empty_transaction_info_is_pending_not_missing', async () => {
    // An unmined transaction resolves to {} despite the declared type.
    const { view } = setup({ client: fakeClient({ txInfo: {} }) })
    await act(async () => void (await view.result.current.pay()))

    await waitFor(() =>
      expect(view.result.current.status).toMatchObject({
        kind: 'processing',
        inclusion: 'pending',
      }),
    )
  })

  it('revert_and_out_of_energy_surface_their_reason', async () => {
    const reverted = setup({
      client: fakeClient({
        txInfo: { blockNumber: 1, receipt: { result: 'REVERT' }, resMessage: 'boom' },
      }),
    })
    await act(async () => void (await reverted.view.result.current.pay()))
    await waitFor(() =>
      expect(reverted.view.result.current.status).toMatchObject({
        kind: 'failed',
        reason: 'tx_reverted',
        txid: TXID,
      }),
    )

    const starved = setup({
      client: fakeClient({
        txInfo: { blockNumber: 1, receipt: { result: 'OUT_OF_ENERGY' } },
      }),
    })
    await act(async () => void (await starved.view.result.current.pay()))
    await waitFor(() =>
      expect(starved.view.result.current.status).toMatchObject({
        kind: 'failed',
        reason: 'out_of_energy',
      }),
    )
  })

  it('a successful on-chain receipt is still not paid', async () => {
    // The invariant. SUCCESS on chain means included, nothing more — the
    // merchant's records are what the payer is waiting on.
    const { view } = setup({
      client: fakeClient({ txInfo: { blockNumber: 1, receipt: { result: 'SUCCESS' } } }),
    })
    await act(async () => void (await view.result.current.pay()))

    await waitFor(() =>
      expect(view.result.current.status).toMatchObject({
        kind: 'processing',
        inclusion: 'included',
      }),
    )
    expect(view.result.current.status.kind).not.toBe('paid')
  })
})

describe('the backend is the only route to paid', () => {
  it('paid_is_shown_only_when_the_backend_says_paid', async () => {
    const { view } = setup({
      client: fakeClient({ txInfo: { blockNumber: 1, receipt: { result: 'SUCCESS' } } }),
    })
    await act(async () => void (await view.result.current.pay()))
    await waitFor(() =>
      expect(view.result.current.status).toMatchObject({ inclusion: 'included' }),
    )

    act(() => view.rerender({ paid: true }))

    await waitFor(() =>
      expect(view.result.current.status).toMatchObject({ kind: 'paid', txid: TXID }),
    )
  })

  it('inclusion_timeout_is_informational_and_a_later_paid_status_wins', async () => {
    jest.useFakeTimers()
    try {
      const { view } = setup({ client: fakeClient({ txInfo: {} }) })
      await act(async () => void (await view.result.current.pay()))

      // Push past the inclusion window with the transaction still unseen.
      await act(async () => {
        jest.advanceTimersByTime(120_000)
        await Promise.resolve()
      })
      await act(async () => {
        await Promise.resolve()
      })
      expect(view.result.current.status).toMatchObject({
        kind: 'processing',
        inclusion: 'timeout',
      })

      act(() => view.rerender({ paid: true }))
      // The timeout never became a failure, and the backend overrides it.
      expect(view.result.current.status.kind).toBe('paid')
    } finally {
      jest.useRealTimers()
    }
  })
})
