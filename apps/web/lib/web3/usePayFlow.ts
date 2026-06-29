'use client'

/**
 * lib/web3/usePayFlow.ts — headless on-chain payment state machine for /pay.
 *
 * Encapsulates the proven flow (read quoteFee → read allowance → approve exactly
 * amount+fee → pay → wait for receipt → parse PaymentMade) with zero JSX, so the
 * brand checkout UI renders against `phase` + actions. USDC path is
 * allowance→approve→pay (no permit shortcut), matching the spec's state machine.
 *
 * The CHARGED fee is the on-chain quoteFee; maxFee = quoteFee (WYSIWYG, no buffer
 * — the deployed fee is deterministic, no live FX). The fee read refetches when
 * the payer/allowance changes and again after approval confirms.
 */
import { useCallback, useEffect, useMemo } from 'react'
import {
  useAccount, useChainId, useSwitchChain,
  useReadContract, useWriteContract, useWaitForTransactionReceipt,
} from 'wagmi'
import { erc20Abi, type Address, type Hex } from 'viem'
import { RSENDS_ROUTER_ABI } from '@/lib/rsendsRouterAbi'
import { RSENDS_ROUTER, FEE_COLLECTOR, CHAIN_ID } from './payTokens'
import { parsePaymentReceipt, type ParsedPayment } from './receipt'
import { humanizeTxError } from './humanizeTxError'
import type { PaymentRequest } from './payParams'

export type PayPhase =
  | 'connect'
  | 'wrongNetwork'
  | 'quoting'
  | 'needsApprove'
  | 'approving'
  | 'ready'
  | 'paying'
  | 'confirmed'

export interface PayFlow {
  phase: PayPhase
  address?: Address
  isConnected: boolean
  onCorrectChain: boolean
  chainId: number
  targetChainId: number
  /** on-chain quoteFee in token base units (null until loaded) */
  fee: bigint | null
  total: bigint | null
  maxFee: bigint | null
  needsApproval: boolean
  approveHash?: Hex
  payHash?: Hex
  parsed: ParsedPayment | null
  error: string | null
  busy: boolean
  switchToChain: () => void
  approve: () => void
  pay: () => void
  reset: () => void
}

export function usePayFlow(request: PaymentRequest): PayFlow {
  const { token, amountBaseUnits, merchant, invoiceId } = request
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { switchChain, isPending: switching } = useSwitchChain()
  const onCorrectChain = chainId === CHAIN_ID

  // ── Fee: on-chain quoteFee (authoritative). Readable pre-connect. ──────────
  const { data: quotedFee, refetch: refetchFee } = useReadContract({
    address: RSENDS_ROUTER,
    abi: RSENDS_ROUTER_ABI,
    functionName: 'quoteFee',
    args: [token.address, amountBaseUnits],
    chainId: CHAIN_ID,
  })
  const fee: bigint | null = typeof quotedFee === 'bigint' ? quotedFee : null
  const total: bigint | null = fee != null ? amountBaseUnits + fee : null
  const maxFee: bigint | null = fee // WYSIWYG ceiling == quoted fee

  // ── Allowance (payer → router) ─────────────────────────────────────────────
  const { data: allowance, refetch: refetchAllowance } = useReadContract({
    address: token.address,
    abi: erc20Abi,
    functionName: 'allowance',
    args: address ? [address, RSENDS_ROUTER] : undefined,
    chainId: CHAIN_ID,
    query: { enabled: !!address && onCorrectChain },
  })
  const needsApproval = total != null && (allowance ?? 0n) < total

  // ── Approve tx ─────────────────────────────────────────────────────────────
  const {
    writeContract: writeApprove, data: approveHash,
    isPending: approvePending, error: approveError, reset: resetApprove,
  } = useWriteContract()
  const { isLoading: approveConfirming, isSuccess: approveConfirmed } =
    useWaitForTransactionReceipt({ hash: approveHash, chainId: CHAIN_ID })

  useEffect(() => {
    if (approveConfirmed) {
      refetchAllowance()
      refetchFee()
    }
  }, [approveConfirmed, refetchAllowance, refetchFee])

  // ── Pay tx ───────────────────────────────────────────────────────────────
  const {
    writeContract: writePay, data: payHash,
    isPending: payPending, error: payError, reset: resetPay,
  } = useWriteContract()
  const { data: payReceipt, isLoading: payConfirming, isSuccess: payConfirmed } =
    useWaitForTransactionReceipt({ hash: payHash, chainId: CHAIN_ID })

  const parsed = useMemo<ParsedPayment | null>(
    () => (payReceipt ? parsePaymentReceipt(payReceipt, FEE_COLLECTOR) : null),
    [payReceipt],
  )

  // ── Actions ────────────────────────────────────────────────────────────────
  const switchToChain = useCallback(() => switchChain({ chainId: CHAIN_ID }), [switchChain])

  const approve = useCallback(() => {
    if (total == null) return
    resetApprove()
    writeApprove({
      address: token.address,
      abi: erc20Abi,
      functionName: 'approve',
      args: [RSENDS_ROUTER, total], // exactly amount + fee, never infinite
      chainId: CHAIN_ID,
    })
  }, [writeApprove, resetApprove, token.address, total])

  const pay = useCallback(() => {
    if (maxFee == null) return
    resetPay()
    writePay({
      address: RSENDS_ROUTER,
      abi: RSENDS_ROUTER_ABI,
      functionName: 'pay',
      args: [invoiceId, merchant, token.address, amountBaseUnits, maxFee],
      chainId: CHAIN_ID,
    })
  }, [writePay, resetPay, invoiceId, merchant, token.address, amountBaseUnits, maxFee])

  const reset = useCallback(() => {
    resetApprove()
    resetPay()
  }, [resetApprove, resetPay])

  // ── Derive phase ─────────────────────────────────────────────────────────
  const busy = switching || approvePending || approveConfirming || payPending || payConfirming
  const error = approveError
    ? humanizeTxError(approveError)
    : payError
      ? humanizeTxError(payError)
      : null

  let phase: PayPhase
  if (!isConnected) phase = 'connect'
  else if (!onCorrectChain) phase = 'wrongNetwork'
  else if (payConfirmed) phase = 'confirmed'
  else if (payHash || payPending) phase = 'paying'
  else if (approveHash && (approvePending || approveConfirming)) phase = 'approving'
  else if (fee == null) phase = 'quoting'
  else if (needsApproval) phase = 'needsApprove'
  else phase = 'ready'

  return {
    phase,
    address,
    isConnected,
    onCorrectChain,
    chainId,
    targetChainId: CHAIN_ID,
    fee,
    total,
    maxFee,
    needsApproval,
    approveHash,
    payHash,
    parsed,
    error,
    busy,
    switchToChain,
    approve,
    pay,
    reset,
  }
}
