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
  | 'tx_failed'
  | 'network_error'
  | 'unknown'

export type TronPayStatus =
  | { kind: 'idle' }
  | { kind: 'preflight' }
  | { kind: 'awaiting_signature' }
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

/** Adapter/transport error kinds, mapped to what the payer is shown. */
const FAILURE_FOR: Record<TronErrorKind, TronPayFailure> = {
  user_rejected: 'user_rejected',
  wallet_not_found: 'wallet_not_found',
  wallet_disconnected: 'wallet_disconnected',
  wrong_network: 'wrong_network',
  connection_failed: 'connection_failed',
  sign_failed: 'tx_failed',
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

  /** The hash is submitted at most once per payment, ever. */
  const hintSent = useRef<string | null>(null)

  const fail = useCallback((reason: TronPayFailure, detail: string, txid?: string) => {
    if (alive.current) setStatus({ kind: 'failed', reason, detail, ...(txid ? { txid } : {}) })
  }, [])

  const pay = useCallback(async () => {
    const payer = wallet.address
    const adapter = wallet.adapter
    if (!payer || !adapter) return
    if (!intent.recipient || !intent.amountExact) return

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
      if (!alive.current) return
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
      const amountBaseUnits = toBaseUnits(intent.amountExact, network.usdt.decimals)

      // 3. Balance BEFORE the estimate. Reversing these makes an insufficient
      //    balance surface as an estimation failure.
      const balance = await usdtBalanceOf(tronWeb, network, payer)
      if (!alive.current) return
      if (balance < BigInt(amountBaseUnits)) {
        fail(
          'insufficient_usdt',
          `needs ${intent.amountExact} ${network.usdt.symbol}`,
        )
        return
      }

      // 4. Energy for this exact transfer, then the fee limit it justifies.
      const energyNeeded = await estimateTransferEnergy(
        tronWeb,
        network,
        payer,
        intent.recipient,
        amountBaseUnits,
      )
      const prices = await readResourcePrices(tronWeb)
      if (!alive.current) return

      // Built before the resource check so bandwidth is measured on the real
      // transaction rather than guessed. Building costs nothing and commits to
      // nothing — the signature is the irreversible step, and it is still ahead.
      const unsigned = await buildTransfer(tronWeb, {
        network,
        payer,
        recipient: intent.recipient,
        intentRecipient: intent.recipient,
        amountBaseUnits,
        feeLimit: feeLimitFor(energyNeeded, prices),
      })

      const [resources, balanceSun] = await Promise.all([
        tronWeb.trx.getAccountResources(payer),
        tronWeb.trx.getBalance(payer),
      ])
      if (!alive.current) return

      const computed = quoteResources({
        energyNeeded,
        rawDataHex: unsigned.raw_data_hex,
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

      // 5. Only now is a signature worth asking for.
      setStatus({ kind: 'awaiting_signature' })
      const signed = await adapter.signTransaction(unsigned)
      if (!alive.current) return

      setStatus({ kind: 'broadcasting' })
      const txid = await broadcast(tronWeb, signed)
      if (!alive.current) return

      setStatus({ kind: 'processing', txid, inclusion: 'pending' })
      onBroadcast()

      // The hint, exactly once, and never awaited for a verdict. If it fails —
      // including because the backend route does not exist yet — the payer is
      // unaffected: the transfer is on chain and the poller finds it by
      // scanning the merchant's address, as it does today.
      if (hintSent.current !== txid) {
        hintSent.current = txid
        void doFetch(`/api/pay/${encodeURIComponent(intent.intentId)}/tx-hint`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tx_hash: txid, payer_address: payer }),
        }).catch(() => {
          /* advisory: a failed hint changes nothing about the payment */
        })
      }
    } catch (err) {
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
      txid: prev.kind === 'processing' ? prev.txid : (prev.kind === 'paid' ? prev.txid : null),
    }))
  }, [backendPaid])

  const reset = useCallback(() => setStatus({ kind: 'idle' }), [])

  return { status, quote, pay, reset }
}
