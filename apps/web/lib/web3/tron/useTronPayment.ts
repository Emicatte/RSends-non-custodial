'use client'

/**
 * lib/web3/tron/useTronPayment — the TRON payment state machine.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE: the backend decides what "paid" means.
 * A transaction id is not proof of payment, a successful broadcast is not
 * proof, and a SUCCESS receipt on chain is not proof either — only the intent's
 * own status, observed by the poller and bound by the matcher, is. So the
 * on-chain polling here exists solely to explain a FAILURE early and precisely;
 * it can move the payer to `failed`, and it can never move them to `paid`.
 *
 * Preflight order is fixed and load-bearing. Balance is checked strictly before
 * the energy estimate, because an insufficient balance makes the estimate
 * revert — and a revert read as an energy problem would tell a payer to buy TRX
 * when what they are short of is USDT.
 *
 * TWO THINGS THAT LOOK LIKE DETAILS AND ARE NOT:
 *
 * A TRON transaction expires. The node stamps `expiration` about 60s out and
 * ties the transaction to a recent block via `ref_block`, so the object built
 * during preflight — before the payer has even seen the Pay button — is stale
 * by the time anyone taps it. It is therefore used ONLY to measure bandwidth,
 * and the transaction that gets signed is rebuilt immediately beforehand and
 * extended to a five-minute window.
 *
 * And the payer can change underneath the flow. An `accountsChanged` or
 * `chainChanged` invalidates the preflight and the built transaction, because
 * signing a transaction whose `owner_address` names an account the wallet has
 * since switched away from produces a confusing failure at best. A generation
 * counter, captured at the start and re-checked after every await, makes an
 * in-flight attempt abandon itself rather than finish against a stale payer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { PaymentIntent } from '../paymentIntent'
import { getTronClient } from './tronClient'
import { toCheckoutError, type TronErrorKind } from './tronErrors'
import type { TronNetworkConfig } from './tronNetwork'
import {
  estimateTransferEnergy,
  feeLimitFor,
  quoteResources,
  readResourcePrices,
  usdtBalanceOf,
  type ResourceQuote,
} from './tronResources'
import { broadcast, buildTransfer, toBaseUnits } from './tronTransfer'
import type { TronWalletSession } from './tronWallet'

/**
 * How long a broadcast transaction may go unseen before the page says so.
 * TRON blocks every ~3s and inclusion is normally within one or two, so 90s
 * means something is wrong. It is deliberately informational: the transfer may
 * still land, and the backend is still the truth, so this never becomes a
 * failure.
 */
export const INCLUSION_TIMEOUT_MS = 90_000

/** Cadence for the on-chain receipt poll. One TRON block. */
const RECEIPT_POLL_MS = 3_000

/**
 * How long the payer has to approve, in SECONDS — `extendExpiration` multiplies
 * by 1000 internally, so passing milliseconds here would ask for 5000 minutes
 * and be rejected. Five minutes covers reading a wallet prompt, unlocking a
 * device, and reconsidering once.
 */
const SIGNATURE_WINDOW_SECONDS = 300

/** A stale attempt aborts rather than finishing against a payer who has changed. */
class StaleAttempt extends Error {}

export type TronPayFailure =
  | 'wrong_network'
  | 'insufficient_usdt'
  | 'insufficient_trx'
  | 'user_rejected'
  | 'wallet_disconnected'
  | 'wallet_not_found'
  | 'connection_failed'
  | 'tx_reverted'
  | 'out_of_energy'
  | 'tx_expired'
  | 'tx_failed'
  | 'network_error'
  | 'unknown'

export type TronPayStatus =
  /** No wallet. */
  | { kind: 'idle' }
  /** Wallet present, nothing in flight. Where an invalidated attempt lands. */
  | { kind: 'connected' }
  | { kind: 'preflight' }
  | { kind: 'awaiting_signature' }
  /** The signing window closed; rebuilding and asking once more. */
  | { kind: 'signature_expired' }
  | { kind: 'broadcasting' }
  | {
      kind: 'processing'
      txid: string
      /** `timeout` is informational; the intent poll keeps running regardless. */
      inclusion: 'pending' | 'included' | 'timeout'
    }
  | { kind: 'paid'; txid: string | null }
  | { kind: 'failed'; reason: TronPayFailure; detail: string; txid?: string }
  | { kind: 'expired' }
  | { kind: 'already_paid' }

/** States an identity change is allowed to tear down — all pre-broadcast. */
const INVALIDATES: ReadonlySet<TronPayStatus['kind']> = new Set([
  'idle',
  'connected',
  'preflight',
  'awaiting_signature',
  'signature_expired',
])

/** Adapter/transport error kinds, mapped to what the payer is shown. */
const FAILURE_FOR: Record<TronErrorKind, TronPayFailure> = {
  user_rejected: 'user_rejected',
  wallet_not_found: 'wallet_not_found',
  wallet_disconnected: 'wallet_disconnected',
  wrong_network: 'wrong_network',
  connection_failed: 'connection_failed',
  sign_failed: 'tx_failed',
  // Reached only once the bounded rebuild has been spent; until then the hook
  // intercepts `tx_expired` and retries rather than failing.
  tx_expired: 'tx_expired',
  broadcast_failed: 'tx_failed',
  network_error: 'network_error',
  unknown: 'unknown',
}

export interface UseTronPaymentDeps {
  /** From `usePaymentIntent`. The only thing that may produce `paid`. */
  backendPaid: boolean
  /** Called once after a successful broadcast, to accelerate the intent poll. */
  onBroadcast: () => void
  /** Test seam. */
  getClient?: typeof getTronClient
  /** Test seam. */
  fetchImpl?: typeof fetch
}

export interface UseTronPaymentResult {
  status: TronPayStatus
  /** What the fee check found, once preflight has run. */
  quote: ResourceQuote | null
  pay: () => Promise<void>
  /** Clear a recoverable failure so the payer can try again. */
  reset: () => void
}

export function useTronPayment(
  intent: PaymentIntent,
  network: TronNetworkConfig,
  wallet: TronWalletSession,
  deps: UseTronPaymentDeps,
): UseTronPaymentResult {
  const [status, setStatus] = useState<TronPayStatus>({ kind: 'idle' })
  const [quote, setQuote] = useState<ResourceQuote | null>(null)

  const { backendPaid, onBroadcast, getClient = getTronClient, fetchImpl } = deps
  // Memoised so `pay` is not rebuilt on every render. The wrapper keeps `fetch`
  // bound to the global, which an unbound reference loses in some environments.
  const doFetch = useMemo<typeof fetch>(
    () => fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a)),
    [fetchImpl],
  )

  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  /** Bumped whenever the connected identity changes. */
  const generation = useRef(0)
  /** The hash is submitted at most once per payment, ever. */
  const hintSent = useRef<string | null>(null)

  const fail = useCallback((reason: TronPayFailure, detail: string, txid?: string) => {
    if (alive.current) setStatus({ kind: 'failed', reason, detail, ...(txid ? { txid } : {}) })
  }, [])

  // Resting state follows the wallet: connected when there is one, idle when
  // there is not. Only the resting states move, so a payment in flight is never
  // disturbed by a re-render.
  useEffect(() => {
    setStatus((prev) => {
      if (prev.kind === 'idle' && wallet.address) return { kind: 'connected' }
      if (prev.kind === 'connected' && !wallet.address) return { kind: 'idle' }
      return prev
    })
  }, [wallet.address])

  // Read synchronously by the invalidation effect. A `setStatus` updater cannot
  // serve that purpose: React defers it to render time, so an in-flight attempt
  // would sail past its guards before the generation bump landed.
  const statusRef = useRef(status)
  statusRef.current = status

  // Identity change: discard the preflight and the built transaction.
  const identity = `${wallet.address ?? ''}|${wallet.chainId ?? ''}`
  const lastIdentity = useRef(identity)
  useEffect(() => {
    if (lastIdentity.current === identity) return
    lastIdentity.current = identity

    // Anything already signed or broadcast is left alone: that transaction is
    // valid and on its way, and an account switch does not unmake it.
    if (!INVALIDATES.has(statusRef.current.kind)) return

    generation.current += 1
    setQuote(null)
    setStatus(wallet.address ? { kind: 'connected' } : { kind: 'idle' })
  }, [identity, wallet.address])

  const pay = useCallback(async () => {
    const payer = wallet.address
    const adapter = wallet.adapter
    if (!payer || !adapter) return
    if (!intent.recipient || !intent.amountExact) return

    const recipient = intent.recipient
    const gen = generation.current
    /** Abandon rather than finish against a payer who has changed. */
    const guard = () => {
      if (!alive.current || gen !== generation.current) throw new StaleAttempt()
    }

    setStatus({ kind: 'preflight' })
    setQuote(null)

    try {
      // 1. The intent, freshly. `usePaymentIntent.refresh()` is fire-and-forget
      //    and yields nothing to gate on, so this asks directly. A payer who
      //    left the tab open for an hour must not be walked into signing a
      //    transfer against an intent that has since expired or been paid.
      const res = await doFetch(`/api/pay/${encodeURIComponent(intent.intentId)}`, {
        cache: 'no-store',
      })
      const fresh = (await res.json()) as { status?: string; expires_at?: string }
      guard()
      if (fresh.status && fresh.status !== 'pending') {
        setStatus(
          fresh.status === 'expired' || fresh.status === 'cancelled'
            ? { kind: 'expired' }
            : { kind: 'already_paid' },
        )
        return
      }
      if (fresh.expires_at && Date.parse(fresh.expires_at) <= Date.now()) {
        setStatus({ kind: 'expired' })
        return
      }

      // 2. Network. TronLink can be asked; WalletConnect cannot, and there the
      //    chain was constrained when the session was requested — so a null
      //    chainId with chainReadable false is not a failure, and must not be
      //    read as agreement either. Only a readable, mismatching chain fails.
      if (wallet.chainReadable && wallet.chainId !== network.chainId) {
        fail(
          'wrong_network',
          `wallet is on ${wallet.chainId ?? 'an unknown chain'}, this invoice is ${network.label}`,
        )
        return
      }

      const tronWeb = await getClient(network)
      guard()
      const amountBaseUnits = toBaseUnits(intent.amountExact, network.usdt.decimals)

      // 3. Balance BEFORE the estimate. Reversing these makes an insufficient
      //    balance surface as an estimation failure.
      const balance = await usdtBalanceOf(tronWeb, network, payer)
      guard()
      if (balance < BigInt(amountBaseUnits)) {
        fail('insufficient_usdt', `needs ${intent.amountExact} ${network.usdt.symbol}`)
        return
      }

      // 4. Energy for this exact transfer, then the fee limit it justifies.
      const energyNeeded = await estimateTransferEnergy(
        tronWeb,
        network,
        payer,
        recipient,
        amountBaseUnits,
      )
      const prices = await readResourcePrices(tronWeb)
      guard()
      const feeLimit = feeLimitFor(energyNeeded, prices)

      const buildFresh = () =>
        buildTransfer(tronWeb, {
          network,
          payer,
          recipient,
          intentRecipient: recipient,
          amountBaseUnits,
          feeLimit,
        })

      // Built here ONLY to measure bandwidth on the real transaction rather
      // than guess it. This object is deliberately never signed — by the time
      // the payer taps Pay its expiration and ref_block are stale.
      const forMeasurement = await buildFresh()
      const [resources, balanceSun] = await Promise.all([
        tronWeb.trx.getAccountResources(payer),
        tronWeb.trx.getBalance(payer),
      ])
      guard()

      const computed = quoteResources({
        energyNeeded,
        rawDataHex: forMeasurement.raw_data_hex,
        // Typed as full by tronweb, delivered partial by TronGrid — which omits
        // zero-valued fields. The double cast is the honest one: the declared
        // type and the wire shape genuinely do not overlap, and pretending the
        // fields are always present is exactly the bug being avoided.
        resources: (resources ?? {}) as unknown as Partial<Record<string, number>>,
        balanceSun: balanceSun ?? 0,
        prices,
      })
      setQuote(computed)
      if (!computed.covered) {
        fail(
          'insufficient_trx',
          `network fees need about ${(computed.costSun / 1_000_000).toFixed(2)} TRX`,
        )
        return
      }

      /** Rebuild, extend, sign, broadcast. One path, both wallets. */
      const attempt = async (): Promise<string> => {
        const unsigned = await buildFresh()
        guard()

        // Five minutes instead of the node's ~60s. Guarded because a tronweb
        // that ever dropped this method should cost a shorter window, not a
        // crash — the transaction is still valid, just briefer.
        const builder = tronWeb.transactionBuilder as {
          extendExpiration?: (tx: unknown, seconds: number) => Promise<unknown>
        }
        const toSign =
          typeof builder.extendExpiration === 'function'
            ? ((await builder.extendExpiration(
                unsigned,
                SIGNATURE_WINDOW_SECONDS,
              )) as typeof unsigned)
            : unsigned
        guard()

        setStatus({ kind: 'awaiting_signature' })
        const signed = await adapter.signTransaction(toSign)
        guard()

        setStatus({ kind: 'broadcasting' })
        return broadcast(tronWeb, signed)
      }

      let txid: string
      try {
        txid = await attempt()
      } catch (err) {
        if (err instanceof StaleAttempt) throw err
        if (toCheckoutError(err).kind !== 'tx_expired') throw err
        // The window closed between building and broadcasting. Rebuild and ask
        // once more — bounded to a single retry, so this can never loop.
        guard()
        setStatus({ kind: 'signature_expired' })
        txid = await attempt()
      }
      guard()

      setStatus({ kind: 'processing', txid, inclusion: 'pending' })
      onBroadcast()

      if (hintSent.current !== txid) {
        hintSent.current = txid
        void submitHint(doFetch, intent.intentId, txid, payer)
      }
    } catch (err) {
      if (err instanceof StaleAttempt) {
        // The payer changed underneath us. Not a failure — just start over.
        if (alive.current) {
          setQuote(null)
          setStatus(wallet.address ? { kind: 'connected' } : { kind: 'idle' })
        }
        return
      }
      const normalised = toCheckoutError(err)
      fail(FAILURE_FOR[normalised.kind], normalised.detail)
    }
  }, [intent, network, wallet, doFetch, getClient, onBroadcast, fail])

  // On-chain receipt watch. Explains a failure early and precisely; never
  // promotes anyone to paid.
  useEffect(() => {
    if (status.kind !== 'processing' || status.inclusion !== 'pending') return
    const { txid } = status
    let cancelled = false
    const startedAt = Date.now()

    const tick = async () => {
      try {
        const tronWeb = await getClient(network)
        const info = (await tronWeb.trx.getTransactionInfo(txid)) as {
          blockNumber?: number
          receipt?: { result?: string }
          resMessage?: string
        }
        if (cancelled || !alive.current) return

        // An unmined transaction resolves to `{}` despite the declared type.
        // That is PENDING, not missing — treating it as not-found would tell a
        // payer their transfer vanished seconds after they sent it.
        if (!info || info.blockNumber === undefined) {
          if (Date.now() - startedAt > INCLUSION_TIMEOUT_MS) {
            setStatus({ kind: 'processing', txid, inclusion: 'timeout' })
          }
          return
        }

        const result = info.receipt?.result
        if (result === 'OUT_OF_ENERGY') {
          fail('out_of_energy', 'the transaction ran out of energy', txid)
        } else if (result && result !== 'SUCCESS') {
          fail(
            result === 'REVERT' ? 'tx_reverted' : 'tx_failed',
            info.resMessage ? `${result}: ${info.resMessage}` : result,
            txid,
          )
        } else {
          // Included and successful on chain — but still not `paid`. That word
          // belongs to the backend.
          setStatus({ kind: 'processing', txid, inclusion: 'included' })
        }
      } catch {
        // A node we cannot reach says nothing about the payment. Stay pending;
        // the intent poll is the path that matters.
      }
    }

    void tick()
    const id = setInterval(() => void tick(), RECEIPT_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [status, network, getClient, fail])

  // The backend's word, and the only route to `paid`. Deliberately last and
  // unconditional on the local state: it overrides an inclusion timeout, an
  // unreachable node, and anything the receipt watch concluded.
  useEffect(() => {
    if (!backendPaid) return
    setStatus((prev) => ({
      kind: 'paid',
      txid:
        prev.kind === 'processing'
          ? prev.txid
          : prev.kind === 'paid'
            ? prev.txid
            : null,
    }))
  }, [backendPaid])

  const reset = useCallback(
    () => setStatus(wallet.address ? { kind: 'connected' } : { kind: 'idle' }),
    [wallet.address],
  )

  return { status, quote, pay, reset }
}

/** Attempts per hint submission, and the backoff between them. */
export const HINT_ATTEMPTS = 3
const HINT_BACKOFF_MS = [400, 1_600]

/**
 * Tell the backend which transaction to look at.
 *
 * Retried because the write is idempotent by construction — the hint table has
 * UNIQUE(intent_id, tx_hash) — so a repeat is free, while a lost hint costs the
 * payer a minute of poller latency for no reason.
 *
 * It remains advisory throughout: when the attempts are exhausted the payment
 * is exactly as it was, because the transfer is already on chain and the poller
 * finds it by scanning the merchant's address.
 */
async function submitHint(
  doFetch: typeof fetch,
  intentId: string,
  txid: string,
  payer: string,
): Promise<void> {
  for (let attempt = 0; attempt < HINT_ATTEMPTS; attempt++) {
    try {
      const res = await doFetch(`/api/pay/${encodeURIComponent(intentId)}/tx-hint`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tx_hash: txid, payer_address: payer }),
      })
      // A 4xx is the backend declining this hint on its merits; repeating it
      // would only ask the same question again.
      if (res.ok || (res.status >= 400 && res.status < 500)) return
    } catch {
      // Transport failure. Fall through to the backoff and try again.
    }
    const wait = HINT_BACKOFF_MS[attempt]
    if (wait !== undefined) await new Promise((r) => setTimeout(r, wait))
  }
}
