'use client'

/**
 * lib/web3/useHostedCheckout — the central hook owning the hosted checkout's
 * wallet flow. Composes wagmi reads/writes and feeds the pure deriver
 * (checkoutState.deriveCheckoutStep); the components render `step`, never
 * their own flags. Never imports RainbowKit (the Connect button is passed
 * into the view as a slot), so the hook is testable with a plain wagmi mock.
 *
 * Flow policy (see checkoutState.ts for precedence):
 * - eip2612 tokens: permit is PRIMARY — one signature + one payWithPermit
 *   transaction, no approve step ever; a rejected signature is recoverable
 *   via retry() (no silent downgrade to approve+pay).
 * - other ERC-20s: approve exactly amount + fee (never infinite), then pay.
 * - native: payNative with value = total.
 * The fee/total/maxFee triple comes from resolveFeeBreakdown — the single
 * source both the summary rows and every transaction argument consume.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  useAccount,
  useBalance,
  useChainId,
  useReadContract,
  useSignTypedData,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from 'wagmi'
import { erc20Abi, zeroAddress } from 'viem'
import { RSENDS_ROUTER_ABI } from '@/lib/rsendsRouterAbi'
import { RSENDS_ROUTER_V2_ABI } from '@/lib/rsendsRouterV2Abi'
import { RSENDS_SPLIT_ROUTER_ABI } from '@/lib/rsendsSplitRouterAbi'
import { resolveFeeBreakdown } from '@/lib/web3/feeMath'
import {
  deriveCheckoutStep,
  type CheckoutStep,
} from '@/lib/web3/checkoutState'
import {
  isTransientNetworkError,
  isUserRejection,
} from '@/lib/web3/humanizeTxError'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'
import {
  EIP2612_ABI,
  buildPermitTypedData,
  permitDeadline,
  splitPermitSignature,
} from '@/lib/web3/permit'

const BALANCE_REFETCH_MS = 15_000

/**
 * How long a sent transaction may sit without a receipt before the checkout
 * stops claiming it is merely "waiting for the network" and says the outcome
 * cannot be confirmed.
 *
 * This exists because `useWaitForTransactionReceipt` does NOT report an error
 * when the chain stops answering: viem's waitForTransactionReceipt retries
 * transport failures indefinitely (measured against a blocked RPC: ~450
 * retries over three minutes, `error` never set). Without a clock of our own
 * the payer would sit on "Waiting for the network" for the whole outage.
 *
 * 45s is far outside normal on Base (2s blocks), so on a healthy chain the
 * message is never reached; and it is self-correcting either way, since a
 * receipt that does land outranks it in the deriver.
 */
const CONFIRMATION_UNKNOWN_AFTER = 45_000

export interface HostedCheckoutDeps {
  /** backend reflects the payment (from usePaymentIntent) */
  backendPaid: boolean
  /** called exactly once when the pay tx mines → start sync polling */
  onMined: () => void
}

export interface HostedCheckout {
  step: CheckoutStep
  isNative: boolean
  usesPermit: boolean
  fee: bigint | null
  total: bigint | null
  maxFee: bigint | null
  balance: bigint | null
  approveHash: `0x${string}` | null
  payHash: `0x${string}` | null
  switchNetwork: () => void
  approve: () => void
  pay: () => Promise<void>
  retry: () => void
  /** re-run the chain reads (manual control for chain_unreachable) */
  retryReads: () => void
  /** raw error text for the collapsed support detail; never a headline */
  errorDetail: string | null
}

export function useHostedCheckout(
  onchain: OnChainIntent,
  deps: HostedCheckoutDeps,
): HostedCheckout {
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { switchChain } = useSwitchChain()

  const isNative = onchain.token === zeroAddress
  const onCorrectChain = chainId === onchain.chainId
  // STATIC policy from the intent: permit iff the registry says eip2612.
  const usesPermit = !isNative && onchain.permitType === 'eip2612'
  // Split fan-out: onchain.router IS the fee-less RSendsSplitRouter and the
  // backend always quotes fee "0" — every other prerequisite (allowance,
  // balance, permit, receipts) runs identically to the single path.
  const split = onchain.split ?? null
  // RSendsRouterV2 (fee-less, ownerless): no quoteFee exists and no fee leg
  // exists in the flow — fee is STRUCTURALLY 0 (never null), so the checkout
  // can never hang quoting against a contract that has nothing to quote.
  const isV2 = onchain.routerVersion === 2

  // ── Fee: prefer the backend's live quoteFee; else read it on-chain.
  //    (Split and v2 intents never reach this read: neither contract has a
  //    quoteFee — split fee is "0" by design, v2 fee is structurally 0.) ──
  const {
    data: quotedFee,
    error: quoteFeeError,
    refetch: refetchQuoteFee,
  } = useReadContract({
    address: onchain.router,
    abi: RSENDS_ROUTER_ABI,
    functionName: 'quoteFee',
    args: [onchain.token, onchain.amount],
    chainId: onchain.chainId,
    query: { enabled: onchain.fee == null && split == null && !isV2 },
  })
  const fee: bigint | null = isV2
    ? 0n
    : (onchain.fee ?? ((quotedFee as bigint | undefined) ?? null))
  const breakdown = resolveFeeBreakdown(onchain.amount, fee)
  const total = breakdown?.total ?? null
  const maxFee = breakdown?.maxFee ?? null

  // ── Allowance — approve+pay fallback path only ──
  const {
    data: allowance,
    error: allowanceError,
    refetch: refetchAllowance,
  } = useReadContract({
    address: onchain.token,
    abi: erc20Abi,
    functionName: 'allowance',
    args: address ? [address, onchain.router] : undefined,
    chainId: onchain.chainId,
    query: { enabled: !isNative && !usesPermit && !!address && onCorrectChain },
  })

  // ── Payer balance — drives insufficient_balance (rechecked periodically
  //    and re-keyed on wallet change) ──
  const { data: tokenBalance } = useReadContract({
    address: onchain.token,
    abi: erc20Abi,
    functionName: 'balanceOf',
    args: address ? [address] : undefined,
    chainId: onchain.chainId,
    query: {
      enabled: !isNative && !!address && onCorrectChain,
      refetchInterval: BALANCE_REFETCH_MS,
    },
  })
  const { data: nativeBalance } = useBalance({
    address,
    chainId: onchain.chainId,
    query: {
      enabled: isNative && !!address && onCorrectChain,
      refetchInterval: BALANCE_REFETCH_MS,
    },
  })
  const balance: bigint | null = isNative
    ? (nativeBalance?.value ?? null)
    : ((tokenBalance as bigint | undefined) ?? null)

  // ── Permit prerequisites (nonce + EIP-712 domain name) ──
  const {
    data: permitNonce,
    error: permitNonceError,
    refetch: refetchPermitNonce,
  } = useReadContract({
    address: onchain.token,
    abi: EIP2612_ABI,
    functionName: 'nonces',
    args: address ? [address] : undefined,
    chainId: onchain.chainId,
    query: { enabled: usesPermit && !!address && onCorrectChain },
  })
  const {
    data: tokenName,
    error: tokenNameError,
    refetch: refetchTokenName,
  } = useReadContract({
    address: onchain.token,
    abi: EIP2612_ABI,
    functionName: 'name',
    chainId: onchain.chainId,
    query: { enabled: usesPermit && onCorrectChain },
  })
  const permitReady =
    !usesPermit || (permitNonce != null && typeof tokenName === 'string')

  // ── Chain reachability ──────────────────────────────────────────
  // Only the reads REQUIRED to build a valid transaction count. A failing
  // balance read stays non-blocking, exactly as an unknown balance always
  // has: it can only produce a false negative, never an invalid tx.
  //
  // Before this existed, every read discarded its `error`, so an unreadable
  // chain looked identical to a slow one and the deriver reported `quoting`
  // forever — the payer saw a spinner on a disabled Pay button, with no
  // explanation, for as long as the outage lasted (2026-08-22).
  const readError = quoteFeeError ?? allowanceError ?? permitNonceError ?? tokenNameError ?? null
  const chainUnreachable = readError != null

  // ── Approve tx ──
  const {
    writeContract: writeApprove,
    data: approveHash,
    isPending: approvePending,
    error: approveError,
    reset: resetApprove,
  } = useWriteContract()
  const { data: approveReceipt } = useWaitForTransactionReceipt({
    hash: approveHash,
    chainId: onchain.chainId,
  })
  const approveConfirmed = approveReceipt?.status === 'success'

  useEffect(() => {
    if (approveConfirmed) void refetchAllowance()
  }, [approveConfirmed, refetchAllowance])

  // ── Pay tx (permit signature counts as part of the wallet prompt) ──
  const {
    writeContract: writePay,
    data: payHash,
    isPending: payPending,
    error: payError,
    reset: resetPay,
  } = useWriteContract()
  const { data: payReceipt, error: payReceiptError } =
    useWaitForTransactionReceipt({
      hash: payHash,
      chainId: onchain.chainId,
    })
  const {
    signTypedDataAsync,
    isPending: signing,
    error: signError,
    reset: resetSign,
  } = useSignTypedData()

  const payMined = payReceipt != null
  const payReverted = payReceipt?.status === 'reverted'

  // ── Error classification ────────────────────────────────────────
  // payer-cancel is recoverable; a transport fault is transient (nothing was
  // broadcast, so retrying is honest); anything else the chain actually said
  // is terminal.
  const txError = approveError ?? payError ?? signError ?? null
  const userRejected = isUserRejection(txError)
  const sendFailed = txError != null && !userRejected
  const sendFailedTransient = sendFailed && isTransientNetworkError(txError)
  // A sent transaction we cannot resolve: either the receipt lookup errored,
  // or it has simply been unanswered for too long (see the constant — viem
  // retries a dead RPC forever rather than erroring, so the timer is the only
  // signal that actually fires during an outage). Either way the transaction
  // is out there and its outcome is unknown to us — never failed.
  const [payStalled, setPayStalled] = useState(false)
  useEffect(() => {
    setPayStalled(false)
    if (!payHash || payMined) return
    const id = setTimeout(() => setPayStalled(true), CONFIRMATION_UNKNOWN_AFTER)
    return () => clearTimeout(id)
  }, [payHash, payMined])
  const receiptUnreadable =
    (payReceiptError != null || payStalled) && payReceipt == null

  // Mined → hand off to the backend sync polling, exactly once.
  const minedNotifiedRef = useRef(false)
  useEffect(() => {
    if (payMined && !payReverted && !minedNotifiedRef.current) {
      minedNotifiedRef.current = true
      deps.onMined()
    }
  }, [payMined, payReverted, deps])

  const step = deriveCheckoutStep({
    isConnected,
    onCorrectChain,
    usesPermit,
    isNative,
    fee,
    total,
    balance,
    allowance: (allowance as bigint | undefined) ?? null,
    permitReady,
    approvePromptOpen: approvePending,
    approveHash: approveHash ?? null,
    approveConfirmed,
    payPromptOpen: payPending || signing,
    payHash: payHash ?? null,
    payMined,
    payReverted,
    sendFailed,
    sendFailedTransient,
    chainUnreachable,
    receiptUnreadable,
    userRejected,
    backendPaid: deps.backendPaid,
  })

  const switchNetwork = useCallback(() => {
    switchChain({ chainId: onchain.chainId })
  }, [switchChain, onchain.chainId])

  const approve = useCallback(() => {
    if (total == null) return
    resetApprove()
    writeApprove({
      address: onchain.token,
      abi: erc20Abi,
      functionName: 'approve',
      args: [onchain.router, total], // exactly amount + fee, never infinite
      chainId: onchain.chainId,
    })
  }, [writeApprove, resetApprove, onchain, total])

  const pay = useCallback(async () => {
    if (!address || fee == null || total == null || maxFee == null) return
    resetPay()

    if (isNative) {
      if (split) {
        // paySplitNative: value must equal totalAmount exactly. Args carry
        // ONLY total + sharesBps — the contract recomputes per-leg amounts.
        writePay({
          address: onchain.router,
          abi: RSENDS_SPLIT_ROUTER_ABI,
          functionName: 'paySplitNative',
          args: [onchain.invoiceId, onchain.amount, split.recipients, split.sharesBps],
          value: total,
          chainId: onchain.chainId,
        })
        return
      }
      if (isV2) {
        // v2: no maxFee argument; value == exactly amount (total === amount).
        writePay({
          address: onchain.router,
          abi: RSENDS_ROUTER_V2_ABI,
          functionName: 'payNative',
          args: [onchain.invoiceId, onchain.merchant, onchain.amount],
          value: total,
          chainId: onchain.chainId,
        })
        return
      }
      writePay({
        address: onchain.router,
        abi: RSENDS_ROUTER_ABI,
        functionName: 'payNative',
        args: [onchain.invoiceId, onchain.merchant, onchain.amount, maxFee],
        value: total,
        chainId: onchain.chainId,
      })
      return
    }

    if (usesPermit) {
      if (permitNonce == null || typeof tokenName !== 'string') return
      const deadline = permitDeadline(Date.now())
      try {
        const signature = await signTypedDataAsync(
          buildPermitTypedData({
            tokenName,
            version: onchain.permitVersion,
            chainId: onchain.chainId,
            token: onchain.token,
            owner: address,
            spender: onchain.router,
            value: total, // permit covers amount + fee (split: fee-less total == amount)
            nonce: permitNonce as bigint,
            deadline,
          }),
        )
        const { v, r, s } = splitPermitSignature(signature)
        if (split) {
          writePay({
            address: onchain.router,
            abi: RSENDS_SPLIT_ROUTER_ABI,
            functionName: 'paySplitWithPermit',
            args: [
              onchain.invoiceId,
              onchain.token,
              onchain.amount,
              split.recipients,
              split.sharesBps,
              deadline,
              v,
              r,
              s,
            ],
            chainId: onchain.chainId,
          })
          return
        }
        if (isV2) {
          // v2: 8 args — the permit (signed for exactly `amount`) slots
          // straight in with no maxFee word.
          writePay({
            address: onchain.router,
            abi: RSENDS_ROUTER_V2_ABI,
            functionName: 'payWithPermit',
            args: [
              onchain.invoiceId,
              onchain.merchant,
              onchain.token,
              onchain.amount,
              deadline,
              v,
              r,
              s,
            ],
            chainId: onchain.chainId,
          })
          return
        }
        writePay({
          address: onchain.router,
          abi: RSENDS_ROUTER_ABI,
          functionName: 'payWithPermit',
          args: [
            onchain.invoiceId,
            onchain.merchant,
            onchain.token,
            onchain.amount,
            maxFee,
            deadline,
            v,
            r,
            s,
          ],
          chainId: onchain.chainId,
        })
      } catch {
        // Rejected/failed signature — classified via signError above.
      }
      return
    }

    // Approve+pay fallback: pay()/paySplit() against the allowance approved above.
    if (split) {
      writePay({
        address: onchain.router,
        abi: RSENDS_SPLIT_ROUTER_ABI,
        functionName: 'paySplit',
        args: [onchain.invoiceId, onchain.token, onchain.amount, split.recipients, split.sharesBps],
        chainId: onchain.chainId,
      })
      return
    }
    if (isV2) {
      writePay({
        address: onchain.router,
        abi: RSENDS_ROUTER_V2_ABI,
        functionName: 'pay',
        args: [onchain.invoiceId, onchain.merchant, onchain.token, onchain.amount],
        chainId: onchain.chainId,
      })
      return
    }
    writePay({
      address: onchain.router,
      abi: RSENDS_ROUTER_ABI,
      functionName: 'pay',
      args: [onchain.invoiceId, onchain.merchant, onchain.token, onchain.amount, maxFee],
      chainId: onchain.chainId,
    })
  }, [
    writePay,
    resetPay,
    onchain,
    isNative,
    usesPermit,
    split,
    isV2,
    fee,
    total,
    maxFee,
    permitNonce,
    tokenName,
    address,
    signTypedDataAsync,
  ])

  const retry = useCallback(() => {
    resetApprove()
    resetPay()
    resetSign()
  }, [resetApprove, resetPay, resetSign])

  // Manual retry for the READ side. React Query already retries each read
  // twice on its own (see app/providers.tsx) and then gives up; this is the
  // control that gives the payer something to press instead of a spinner.
  // Disabled queries no-op, so calling them all is safe on every path.
  const retryReads = useCallback(() => {
    void refetchQuoteFee()
    void refetchAllowance()
    void refetchPermitNonce()
    void refetchTokenName()
  }, [refetchQuoteFee, refetchAllowance, refetchPermitNonce, refetchTokenName])

  return {
    step,
    isNative,
    usesPermit,
    fee,
    total,
    maxFee,
    balance,
    approveHash: approveHash ?? null,
    payHash: payHash ?? null,
    switchNetwork,
    approve,
    pay,
    retry,
    retryReads,
    errorDetail: errorDetailOf(readError ?? payReceiptError ?? txError),
  }
}

/** First line of the raw error, bounded. Support-facing only. */
function errorDetailOf(err: unknown): string | null {
  if (err == null) return null
  const raw = err instanceof Error ? err.message : String(err)
  return raw.split('\n')[0].slice(0, 160) || null
}
