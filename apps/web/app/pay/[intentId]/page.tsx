'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import dynamic from 'next/dynamic'
import { QueryClient } from '@tanstack/react-query'
import {
  useAccount, useChainId, useSwitchChain,
  useReadContract, useWriteContract, useWaitForTransactionReceipt, useSignTypedData,
} from 'wagmi'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { erc20Abi, getAddress, zeroAddress, formatUnits, parseSignature, type Hex } from 'viem'
import { RSENDS_ROUTER_ABI } from '@/lib/rsendsRouterAbi'
import { getRegistry } from '@/lib/contractRegistry'
import { requireEnv } from '@/lib/env'

// The /pay route is intentionally OUTSIDE the wallet `Providers` (see
// app/providers.tsx line ~79 which bypasses /pay) AND outside the
// NextIntlClientProvider (middleware excludes /pay). So we:
//   1. mount the full wallet stack ourselves here, and
//   2. use plain English strings (no next-intl) — matching the prior page.
const WalletStackFull = dynamic(() => import('@/app/providers-wallet-stack'), { ssr: false })

// ═══════════════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════════════

/**
 * Payment intent as served by GET /api/pay/{intentId}.
 *
 * TODO(backend): the create-intent / get-intent endpoint must now return the
 * non-custodial on-chain fields below (camelCase). Until the backend ships
 * them we read both shapes defensively (see `normalizeIntent`):
 *   - invoiceId  bytes32  — the contract invoice id for pay()/payNative()
 *   - merchant   address  — settlement recipient
 *   - token      address  — ERC20 address, or 0x0 for native ETH
 *   - amount     string   — base units / wei (decimal string)
 *   - chainId    number   — EVM chain id the router lives on
 *   - router     address  — RSendsRouter address for this chain
 * Legacy custodial fields (deposit_address, etc.) are ignored by this flow.
 */
interface RawPaymentIntent {
  // identity / status (existing)
  intent_id?: string
  reference_id?: string
  status: string
  expires_at: string
  // legacy custodial display fields (still used for amount/currency labels)
  amount?: number | string
  currency?: string
  chain?: string
  // settlement tx surfaced by the indexer once PaymentMade is seen
  matched_tx_hash?: string | null
  tx_hash?: string | null
  metadata?: Record<string, unknown> | null
  // Public limited view (GET /api/v1/public/payment-intent): the backend
  // derives the display name server-side; the metadata dict stays private.
  merchant_name?: string | null
  // ── NEW non-custodial on-chain fields ───────────────────────────────────
  // The backend nests these under `onchain` (PaymentIntentResponse.onchain).
  onchain?: {
    invoiceId?: string
    merchant?: string
    token?: string
    amount?: string // base units (wei / token decimals)
    fee?: string | null // base units; null when the backend couldn't quote it (feeUnavailable)
    total?: string | null // amount + fee
    maxFee?: string | null // payer ceiling (== fee)
    chainId?: number
    router?: string
    calldata?: string | null
    payWithPermitCalldata?: string | null
    function?: string
    decimals?: number
    isNative?: boolean
    permitType?: string | null
    permitVersion?: string | null
    feeUnavailable?: boolean
  } | null
  // Top-level camelCase also tolerated (alternate backend shape).
  invoiceId?: string
  merchant?: string
  token?: string
  amount_base_units?: string
  chainId?: number
  router?: string
}

interface OnChainIntent {
  invoiceId: Hex
  merchant: `0x${string}`
  token: `0x${string}`
  amount: bigint
  /** fee in token base units from the backend's live quoteFee; null → read quoteFee on-chain */
  fee: bigint | null
  /** token decimals — for formatting the fee/total breakdown */
  decimals: number
  chainId: number
  router: `0x${string}`
  /** STATIC permit policy from the registry: "eip2612" → permit flow, else approve+pay. */
  permitType: 'eip2612' | 'none'
  /** EIP-712 domain version for the permit signature (only meaningful for eip2612). */
  permitVersion: string
}

interface PaymentIntent {
  intentId: string
  status: string
  expiresAt: string
  amountLabel: string
  currency: string
  chainLabel: string
  txHash: string | null
  metadata: Record<string, unknown> | null
  /** present only when the backend has shipped the on-chain fields */
  onchain: OnChainIntent | null
  /** raw payload kept for debugging / future fields */
  raw: RawPaymentIntent
}

type PageState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'not_found' }
  | { kind: 'ready'; intent: PaymentIntent }

// ═══════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════

const POLL_INTERVAL = 5_000
const WS_RECONNECT_DELAY = 3_000
const WS_MAX_RECONNECTS = 5

type ConnectionMode = 'connecting' | 'live' | 'polling'

const CHAIN_LABELS: Record<string, string> = {
  BASE: 'Base', ETH: 'Ethereum', ARBITRUM: 'Arbitrum', OPTIMISM: 'Optimism',
  POLYGON: 'Polygon', BSC: 'BNB Chain', AVALANCHE: 'Avalanche',
  BASE_SEPOLIA: 'Base Sepolia', SEPOLIA: 'Sepolia',
}

// Status set: backend uses 'pending' | 'completed' | 'expired' | 'cancelled'.
// TODO(backend): the new contract spec uses 'paid' for success — we treat both
// 'completed' and 'paid' as the success terminal state below.
const PAID_STATES = new Set(['completed', 'paid'])
const DEAD_STATES = new Set(['expired', 'cancelled'])

// ═══════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════

function formatCountdown(ms: number): string {
  if (ms <= 0) return '0:00'
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** Block-explorer tx link, sourced from contractRegistry by chainId. */
function explorerTxLink(chainId: number | null, hash: string): string {
  const reg = chainId != null ? getRegistry(chainId) : null
  const base = reg?.blockExplorer ?? 'https://basescan.org'
  return `${base.replace(/\/$/, '')}/tx/${hash}`
}

function chainName(chainId: number | null, fallbackLabel: string): string {
  if (chainId == null) return fallbackLabel
  const reg = getRegistry(chainId)
  return reg?.chainName ?? fallbackLabel
}

/**
 * Normalize the raw backend payload into a stable shape and, when the new
 * on-chain fields are present, build a typed OnChainIntent for the Pay flow.
 */
function normalizeIntent(raw: RawPaymentIntent, intentId: string): PaymentIntent {
  const chainLabel = raw.chain
    ? (CHAIN_LABELS[raw.chain.toUpperCase()] ?? raw.chain)
    : 'Base'

  // Build on-chain block only if the backend supplied the required fields.
  // Prefer the nested `onchain` object (PaymentIntentResponse.onchain); fall
  // back to top-level camelCase fields for alternate backend shapes.
  let onchain: OnChainIntent | null = null
  const oc = raw.onchain ?? null
  const invoiceId = oc?.invoiceId ?? raw.invoiceId
  const merchant = oc?.merchant ?? raw.merchant
  const token = oc?.token ?? raw.token
  const amountStr =
    oc?.amount ?? raw.amount_base_units ?? (typeof raw.amount === 'string' ? raw.amount : undefined)
  const chainId = oc?.chainId ?? raw.chainId
  const router = oc?.router ?? raw.router
  if (
    invoiceId && merchant && token != null &&
    amountStr != null && chainId != null && router
  ) {
    try {
      onchain = {
        invoiceId: invoiceId as Hex,
        merchant: getAddress(merchant),
        token: getAddress(token),
        amount: BigInt(amountStr),
        // fee may be absent (feeUnavailable / alternate shape) → null, PayPanel
        // then reads quoteFee on-chain.
        fee: oc?.fee != null ? BigInt(oc.fee) : null,
        decimals: oc?.decimals ?? 18,
        chainId: chainId,
        router: getAddress(router),
        // STATIC permit policy from the registry (default to approve+pay if absent).
        permitType: oc?.permitType === 'eip2612' ? 'eip2612' : 'none',
        permitVersion: oc?.permitVersion ?? '1',
      }
    } catch {
      // Malformed on-chain fields → fall back to "not available" UI.
      onchain = null
    }
  }

  return {
    intentId,
    status: raw.status,
    expiresAt: raw.expires_at,
    amountLabel: raw.amount != null ? String(raw.amount) : '',
    currency: raw.currency ?? '',
    chainLabel,
    txHash: raw.matched_tx_hash || raw.tx_hash || null,
    metadata: raw.metadata ?? null,
    onchain,
    raw,
  }
}

function merchantName(intent: PaymentIntent): string {
  // Public limited view: server-derived display name (metadata not exposed).
  if (intent.raw.merchant_name) return intent.raw.merchant_name
  // Legacy shape: derive from the metadata dict if the backend sent one.
  const meta = intent.metadata
  if (!meta) return 'RSends Payment'
  return (meta.merchant_name as string) || (meta.store_name as string) || 'RSends Payment'
}

// ═══════════════════════════════════════════════════════════════
//  WebSocket Hook — real-time payment updates with polling fallback
//  (unchanged from the custodial flow: the indexer flips status to
//  paid/completed once it observes the PaymentMade event on-chain)
// ═══════════════════════════════════════════════════════════════

function usePaymentWebSocket(
  intentId: string,
  status: string | null,
  onEvent: (event: { event: string; tx_hash?: string }) => void,
): ConnectionMode {
  const [mode, setMode] = useState<ConnectionMode>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectsRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    // Only connect while pending
    if (status !== 'pending') {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      return
    }

    function connect() {
      if (!mountedRef.current) return

      // TODO: WebSocket call is direct-to-backend; consider an edge/Node
      // proxy so NEXT_PUBLIC_RPAGOS_BACKEND_URL can become server-only.
      const backendUrl = requireEnv('NEXT_PUBLIC_RPAGOS_BACKEND_URL')
      const wsUrl = backendUrl.replace(/^http/, 'ws') + `/ws/payment/${intentId}`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        reconnectsRef.current = 0
        setMode('live')
      }

      ws.onmessage = (ev) => {
        if (!mountedRef.current) return
        try {
          const data = JSON.parse(ev.data)
          if (data.event === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }))
            return
          }
          // TODO(backend): keep emitting payment.completed (or a new
          // payment.paid alias) when the indexer sees PaymentMade.
          if (data.event === 'payment.completed' || data.event === 'payment.paid' || data.event === 'payment.expired') {
            onEvent(data)
          }
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        wsRef.current = null
        setMode('polling')
        if (reconnectsRef.current < WS_MAX_RECONNECTS) {
          reconnectsRef.current += 1
          setTimeout(connect, WS_RECONNECT_DELAY)
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setMode('polling')
      }
    }

    connect()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [intentId, status, onEvent])

  return mode
}

// ═══════════════════════════════════════════════════════════════
//  Page entry — mounts the wallet stack (wagmi + RainbowKit) since the
//  global Providers skips /pay routes.
// ═══════════════════════════════════════════════════════════════

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 8_000, retry: 2 } },
  })
}

export default function CheckoutPage() {
  const [queryClient] = useState(makeQueryClient)

  return (
    <WalletStackFull
      autoOpenModal={false}
      reconnectOnMount={true}
      queryClient={queryClient}
    >
      <CheckoutInner />
    </WalletStackFull>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Inner component — has wagmi/RainbowKit context available
// ═══════════════════════════════════════════════════════════════

function CheckoutInner() {
  const params = useParams<{ intentId: string }>()
  const intentId = params.intentId

  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [prevStatus, setPrevStatus] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Fetch intent ─────────────────────────────────────────
  const fetchIntent = useCallback(async () => {
    try {
      const res = await fetch(`/api/pay/${intentId}`)
      if (res.status === 404) {
        setState({ kind: 'not_found' })
        return null
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setState({ kind: 'error', message: body.message || `Error ${res.status}` })
        return null
      }
      const data: RawPaymentIntent = await res.json()
      const intent = normalizeIntent(data, intentId)
      setState({ kind: 'ready', intent })
      return intent
    } catch {
      setState({ kind: 'error', message: 'Network error. Please try again.' })
      return null
    }
  }, [intentId])

  useEffect(() => { fetchIntent() }, [fetchIntent])

  // ── WebSocket — real-time updates ────────────────────────
  const currentStatus = state.kind === 'ready' ? state.intent.status : null

  const handleWsEvent = useCallback((_event: { event: string; tx_hash?: string }) => {
    // Any terminal event → re-fetch to pull tx_hash / final status.
    fetchIntent()
  }, [fetchIntent])

  const connectionMode = usePaymentWebSocket(intentId, currentStatus, handleWsEvent)

  // ── Polling — fallback when WebSocket is not connected ───
  useEffect(() => {
    if (state.kind !== 'ready') return
    const { status } = state.intent

    if (prevStatus && prevStatus !== status) setPrevStatus(status)
    else if (!prevStatus) setPrevStatus(status)

    if (status !== 'pending') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    if (connectionMode === 'live') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    pollRef.current = setInterval(fetchIntent, POLL_INTERVAL)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [state, fetchIntent, prevStatus, connectionMode])

  // ── Render ───────────────────────────────────────────────
  if (state.kind === 'loading') return <Shell><LoadingView /></Shell>
  if (state.kind === 'not_found') return <Shell><NotFoundView /></Shell>
  if (state.kind === 'error') return <Shell><ErrorView message={state.message} /></Shell>

  const { intent } = state
  const s = intent.status

  if (DEAD_STATES.has(s)) return <Shell><ExpiredView intent={intent} /></Shell>
  if (PAID_STATES.has(s)) return <Shell><CompletedView intent={intent} /></Shell>

  return (
    <Shell>
      <PendingView intent={intent} connectionMode={connectionMode} />
    </Shell>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Pending (Main Checkout UI) — non-custodial Pay flow
// ═══════════════════════════════════════════════════════════════

function PendingView({
  intent,
  connectionMode,
}: {
  intent: PaymentIntent
  connectionMode: ConnectionMode
}) {
  const [remaining, setRemaining] = useState('')
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    function tick() {
      const diff = new Date(intent.expiresAt).getTime() - Date.now()
      if (diff <= 0) { setExpired(true); setRemaining('0:00'); return }
      setRemaining(formatCountdown(diff))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [intent.expiresAt])

  const name = merchantName(intent)

  return (
    <Card>
      {/* Header */}
      <div className="text-center mb-6">
        <div className="mx-auto mb-3 w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
          <svg className="w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z" />
          </svg>
        </div>
        <h1 className="text-base font-semibold text-white">{name}</h1>
      </div>

      {/* Amount */}
      <div className="text-center mb-6">
        <p className="text-3xl font-bold text-white tracking-tight">
          {intent.amountLabel} {intent.currency}
        </p>
        <div className="mt-2 flex items-center justify-center gap-2">
          <ChainBadge label={intent.onchain ? chainName(intent.onchain.chainId, intent.chainLabel) : intent.chainLabel} variant="default" />
          {!expired && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
              style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}
            >
              <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {remaining}
            </span>
          )}
        </div>
      </div>

      <div className="border-t border-white/[0.06] my-5" />

      {/* Pay action — wallet-based, non-custodial */}
      {intent.onchain ? (
        <PayPanel onchain={intent.onchain} amountLabel={intent.amountLabel} currency={intent.currency} />
      ) : (
        <div className="text-center py-6">
          {/* TODO(backend): this branch shows until the get-intent endpoint
              returns invoiceId / merchant / token / amount / chainId / router.
              Once those ship, the on-chain Pay panel renders automatically. */}
          <p className="text-sm text-zinc-500">
            Payment details are not available yet. Please contact the merchant.
          </p>
        </div>
      )}

      <div className="border-t border-white/[0.06] my-5" />

      {/* Waiting indicator with connection status */}
      <div className="flex items-center justify-center gap-2">
        <span
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ background: connectionMode === 'live' ? '#22c55e' : '#eab308' }}
        />
        <span className="text-xs text-zinc-500">Waiting for confirmation...</span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded-full"
          style={{
            background: connectionMode === 'live' ? 'rgba(34,197,94,0.1)' : 'rgba(234,179,8,0.1)',
            color: connectionMode === 'live' ? '#22c55e' : '#eab308',
          }}
        >
          {connectionMode === 'live' ? 'live' : 'polling'}
        </span>
      </div>

      <p className="text-center text-[10px] text-zinc-600 mt-4">
        Payment is confirmed automatically once it settles on-chain
      </p>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Pay Panel — connect / switch-chain / pay (native | permit | approve+pay)
// ═══════════════════════════════════════════════════════════════

// Permit capability is STATIC policy from the token registry, surfaced to the
// frontend as onchain.permitType ("eip2612" → permit flow, else approve()+pay()).
// No runtime "does this token support permit" introspection. The EIP-712 domain
// version also comes from the registry (onchain.permitVersion; Circle tokens = "2").
const EIP2612_ABI = [
  { type: 'function', name: 'nonces', stateMutability: 'view',
    inputs: [{ name: 'owner', type: 'address' }], outputs: [{ name: '', type: 'uint256' }] },
  { type: 'function', name: 'name', stateMutability: 'view',
    inputs: [], outputs: [{ name: '', type: 'string' }] },
] as const

function PayPanel({
  onchain,
  amountLabel,
  currency,
}: {
  onchain: OnChainIntent
  amountLabel: string
  currency: string
}) {
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { switchChain, isPending: switching } = useSwitchChain()

  const isNative = onchain.token === zeroAddress
  const onCorrectChain = chainId === onchain.chainId
  // STATIC: permit flow iff the registry says this token is eip2612 (no introspection).
  const supportsPermit = !isNative && onchain.permitType === 'eip2612'

  // ── Fee: prefer the backend's live quoteFee; else read quoteFee on-chain ──
  const { data: quotedFee } = useReadContract({
    address: onchain.router,
    abi: RSENDS_ROUTER_ABI,
    functionName: 'quoteFee',
    args: [onchain.token, onchain.amount],
    chainId: onchain.chainId,
    query: { enabled: onchain.fee == null },
  })
  const fee: bigint | null = onchain.fee ?? (quotedFee ?? null)
  const total: bigint | null = fee != null ? onchain.amount + fee : null
  const maxFee: bigint | null = fee // payer ceiling == quoted fee
  const fmt = (v: bigint) => formatUnits(v, onchain.decimals)

  // ── Allowance — only the approve+pay path (USDT/DAI) ──────────────────────
  const {
    data: allowance,
    refetch: refetchAllowance,
    isLoading: allowanceLoading,
  } = useReadContract({
    address: onchain.token,
    abi: erc20Abi,
    functionName: 'allowance',
    args: address ? [address, onchain.router] : undefined,
    chainId: onchain.chainId,
    query: { enabled: !isNative && !supportsPermit && !!address && onCorrectChain },
  })
  // Approve EXACTLY amount + fee (never infinite).
  const needsApproval = !isNative && !supportsPermit && total != null && (allowance ?? 0n) < total

  // ── Permit reads (nonce + domain name) for the permit path ────────────────
  const { data: permitNonce } = useReadContract({
    address: onchain.token,
    abi: EIP2612_ABI,
    functionName: 'nonces',
    args: address ? [address] : undefined,
    chainId: onchain.chainId,
    query: { enabled: supportsPermit && !!address && onCorrectChain },
  })
  const { data: tokenName } = useReadContract({
    address: onchain.token,
    abi: EIP2612_ABI,
    functionName: 'name',
    chainId: onchain.chainId,
    query: { enabled: supportsPermit && onCorrectChain },
  })
  const permitReady = !supportsPermit || (permitNonce != null && typeof tokenName === 'string')

  // ── Approve tx ──────────────────────────────────────────────────────────
  const {
    writeContract: writeApprove,
    data: approveHash,
    isPending: approvePending,
    error: approveError,
    reset: resetApprove,
  } = useWriteContract()
  const { isLoading: approveConfirming, isSuccess: approveConfirmed } =
    useWaitForTransactionReceipt({ hash: approveHash, chainId: onchain.chainId })

  useEffect(() => {
    if (approveConfirmed) refetchAllowance()
  }, [approveConfirmed, refetchAllowance])

  // ── Pay tx ──────────────────────────────────────────────────────────────
  const {
    writeContract: writePay,
    data: payHash,
    isPending: payPending,
    error: payError,
    reset: resetPay,
  } = useWriteContract()
  const { isLoading: payConfirming, isSuccess: payConfirmed } =
    useWaitForTransactionReceipt({ hash: payHash, chainId: onchain.chainId })
  const { signTypedDataAsync, isPending: signing, error: signError } = useSignTypedData()

  const doApprove = useCallback(() => {
    if (total == null) return
    resetApprove()
    writeApprove({
      address: onchain.token,
      abi: erc20Abi,
      functionName: 'approve',
      args: [onchain.router, total], // exactly amount + fee
      chainId: onchain.chainId,
    })
  }, [writeApprove, onchain, resetApprove, total])

  const doPay = useCallback(async () => {
    if (!address || fee == null || total == null || maxFee == null) return
    resetPay()

    // Native ETH — value = amount + fee (fee is 0 by default).
    if (isNative) {
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

    // USDC / EURC — EIP-2612 permit in a single tx (no separate approve).
    if (supportsPermit) {
      if (permitNonce == null || typeof tokenName !== 'string') return
      const deadline = BigInt(Math.floor(Date.now() / 1000) + 3600)
      try {
        const signature = await signTypedDataAsync({
          domain: {
            name: tokenName,
            version: onchain.permitVersion,
            chainId: onchain.chainId,
            verifyingContract: onchain.token,
          },
          types: {
            Permit: [
              { name: 'owner', type: 'address' },
              { name: 'spender', type: 'address' },
              { name: 'value', type: 'uint256' },
              { name: 'nonce', type: 'uint256' },
              { name: 'deadline', type: 'uint256' },
            ],
          },
          primaryType: 'Permit',
          message: {
            owner: address,
            spender: onchain.router,
            value: total, // permit covers amount + fee
            nonce: permitNonce,
            deadline,
          },
        })
        const { r, s, yParity } = parseSignature(signature)
        const v = 27 + yParity
        writePay({
          address: onchain.router,
          abi: RSENDS_ROUTER_ABI,
          functionName: 'payWithPermit',
          args: [onchain.invoiceId, onchain.merchant, onchain.token, onchain.amount, maxFee, deadline, v, r, s],
          chainId: onchain.chainId,
        })
      } catch {
        // Signature rejected/failed — surfaced via signError below.
      }
      return
    }

    // USDT / DAI — pay() against the allowance approved above.
    writePay({
      address: onchain.router,
      abi: RSENDS_ROUTER_ABI,
      functionName: 'pay',
      args: [onchain.invoiceId, onchain.merchant, onchain.token, onchain.amount, maxFee],
      chainId: onchain.chainId,
    })
  }, [writePay, onchain, isNative, supportsPermit, resetPay, fee, total, maxFee, permitNonce, tokenName, address, signTypedDataAsync])

  const explorerChain = chainName(onchain.chainId, '')
  const busy = approvePending || approveConfirming || payPending || payConfirming || signing
  const feeLoading = fee == null
  const txError = approveError || payError || signError
  const payLabel = `Pay ${total != null ? fmt(total) : amountLabel} ${currency}`

  // ── Fee breakdown (amount / fee / total) — shown in every state ───────────
  const feeBreakdown = (
    <div className="w-full rounded-lg bg-white/[0.02] border border-white/[0.05] px-3 py-2.5 text-xs space-y-1.5">
      <div className="flex justify-between">
        <span className="text-zinc-500">Amount</span>
        <span className="text-zinc-300">{amountLabel} {currency}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-zinc-500">Fee</span>
        <span className="text-zinc-300">{fee != null ? `${fmt(fee)} ${currency}` : '…'}</span>
      </div>
      <div className="flex justify-between pt-1.5 border-t border-white/[0.05] font-semibold">
        <span className="text-zinc-300">Total</span>
        <span className="text-white">{total != null ? `${fmt(total)} ${currency}` : '…'}</span>
      </div>
    </div>
  )

  // ── State-specific body ───────────────────────────────────────────────────
  let body: React.ReactNode
  if (!isConnected) {
    body = (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm text-zinc-400 text-center">
          Connect your wallet to pay{' '}
          <span className="text-white font-semibold">{total != null ? `${fmt(total)} ${currency}` : `${amountLabel} ${currency}`}</span>{' '}
          directly to the merchant.
        </p>
        <div className="rsends-connect">
          <ConnectButton chainStatus="none" showBalance={false} label="Connect Wallet" />
        </div>
      </div>
    )
  } else if (!onCorrectChain) {
    body = (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm text-zinc-400 text-center">
          Switch your wallet to{' '}
          <span className="text-white font-semibold">{chainName(onchain.chainId, `chain ${onchain.chainId}`)}</span>{' '}
          to complete this payment.
        </p>
        <PrimaryButton
          onClick={() => switchChain({ chainId: onchain.chainId })}
          disabled={switching}
          label={switching ? 'Switching network...' : `Switch to ${chainName(onchain.chainId, `chain ${onchain.chainId}`)}`}
        />
        <div className="rsends-connect-sm">
          <ConnectButton chainStatus="icon" showBalance={false} accountStatus="address" />
        </div>
      </div>
    )
  } else {
    body = (
      <div className="flex flex-col items-center gap-3">
        <div className="rsends-connect-sm self-center mb-1">
          <ConnectButton chainStatus="icon" showBalance={false} accountStatus="address" />
        </div>

        {payConfirming || payHash ? (
          <TxInProgress
            label={payConfirming ? 'Confirming payment...' : 'Payment submitted'}
            hash={payHash}
            explorerLink={payHash ? explorerTxLink(onchain.chainId, payHash) : null}
            confirmed={payConfirmed}
          />
        ) : isNative ? (
          <PrimaryButton
            onClick={doPay}
            disabled={busy || feeLoading}
            label={feeLoading ? 'Loading fee...' : payPending ? 'Confirm in wallet...' : payLabel}
          />
        ) : supportsPermit ? (
          <>
            <PrimaryButton
              onClick={doPay}
              disabled={busy || feeLoading || !permitReady}
              label={signing ? 'Sign in wallet...' : payPending ? 'Confirm in wallet...' : feeLoading ? 'Loading fee...' : payLabel}
            />
            <p className="text-[11px] text-zinc-500 text-center">
              One-tap — sign a permit for {total != null ? fmt(total) : ''} {currency} (amount + fee), no separate approval.
            </p>
          </>
        ) : needsApproval ? (
          <>
            <PrimaryButton
              onClick={doApprove}
              disabled={busy || allowanceLoading || feeLoading}
              label={
                approvePending ? 'Confirm in wallet...'
                : approveConfirming ? 'Approving...'
                : `Approve ${currency || 'token'}`
              }
            />
            {approveHash && (
              <TxLink
                hash={approveHash}
                link={explorerTxLink(onchain.chainId, approveHash)}
                label={approveConfirmed ? 'Approval confirmed' : 'Approval pending'}
              />
            )}
            <p className="text-[11px] text-zinc-500 text-center">
              Step 1 of 2 — approve exactly {total != null ? fmt(total) : ''} {currency || 'tokens'} (amount + fee), then pay.
            </p>
          </>
        ) : (
          <PrimaryButton
            onClick={doPay}
            disabled={busy || feeLoading}
            label={feeLoading ? 'Loading fee...' : payPending ? 'Confirm in wallet...' : payLabel}
          />
        )}

        {txError && (
          <p className="text-xs text-red-400 text-center break-words max-w-full">
            {humanizeTxError(txError)}
          </p>
        )}

        <p className="text-center text-[10px] text-zinc-600">
          Non-custodial — funds go directly to the merchant
          {explorerChain ? ` on ${explorerChain}` : ''}.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-4">
      {feeBreakdown}
      {body}
    </div>
  )
}

function humanizeTxError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)
  if (/user rejected|denied|rejected the request/i.test(raw)) return 'Transaction rejected in wallet.'
  if (/insufficient funds/i.test(raw)) return 'Insufficient funds for gas or amount.'
  // viem wraps the human-readable reason on the first line.
  return raw.split('\n')[0].slice(0, 160)
}

// ═══════════════════════════════════════════════════════════════
//  Small UI pieces
// ═══════════════════════════════════════════════════════════════

function PrimaryButton({ onClick, disabled, label }: { onClick: () => void; disabled?: boolean; label: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full rounded-xl px-4 py-3 text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
      style={{ background: '#00ffa3', color: '#000' }}
    >
      {label}
    </button>
  )
}

function TxLink({ hash, link, label }: { hash: string; link: string; label: string }) {
  return (
    <a
      href={link}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-300 transition-colors"
    >
      <span>{label}:</span>
      <span className="font-mono">{hash.slice(0, 10)}...{hash.slice(-8)}</span>
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
      </svg>
    </a>
  )
}

function TxInProgress({
  label, hash, explorerLink, confirmed,
}: {
  label: string; hash?: string; explorerLink: string | null; confirmed: boolean
}) {
  return (
    <div className="flex flex-col items-center gap-3 w-full">
      {!confirmed && (
        <div className="w-7 h-7 border-2 border-zinc-700 border-t-[#00ffa3] rounded-full animate-spin" />
      )}
      <p className="text-sm text-zinc-300">{label}</p>
      {hash && explorerLink && (
        <TxLink hash={hash} link={explorerLink} label="View tx" />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Shell + status views (loading / not found / error / expired / done)
// ═══════════════════════════════════════════════════════════════

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: '#0a0a0a' }}>
      <div className="w-full max-w-lg">{children}</div>
    </div>
  )
}

function LoadingView() {
  return (
    <Card>
      <div className="flex flex-col items-center gap-4 py-12">
        <div className="w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
        <p className="text-sm text-zinc-500">Loading payment...</p>
      </div>
    </Card>
  )
}

function NotFoundView() {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-10">
        <div className="w-14 h-14 rounded-full bg-zinc-800 flex items-center justify-center">
          <svg className="w-7 h-7 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-white">Payment not found</h2>
        <p className="text-sm text-zinc-500 text-center">
          This payment link is invalid or has been removed.
        </p>
      </div>
    </Card>
  )
}

function ErrorView({ message }: { message: string }) {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-10">
        <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center">
          <svg className="w-7 h-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-white">Something went wrong</h2>
        <p className="text-sm text-zinc-500 text-center">{message}</p>
      </div>
    </Card>
  )
}

function ExpiredView({ intent }: { intent: PaymentIntent }) {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-10">
        <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center">
          <svg className="w-7 h-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-white">
          Payment {intent.status === 'cancelled' ? 'cancelled' : 'expired'}
        </h2>
        <p className="text-sm text-zinc-500 text-center">
          This payment request is no longer active.
          {intent.status === 'expired' && ' It expired before a payment was received.'}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <span className="text-xl font-bold text-zinc-400">
            {intent.amountLabel} {intent.currency}
          </span>
          <ChainBadge label={intent.chainLabel} variant="muted" />
        </div>
      </div>
    </Card>
  )
}

function CompletedView({ intent }: { intent: PaymentIntent }) {
  const txHash = intent.txHash
  const chainId = intent.onchain?.chainId ?? null
  const link = txHash ? explorerTxLink(chainId, txHash) : null

  return (
    <Card>
      <div className="flex flex-col items-center gap-4 py-8 animate-[fadeScale_0.5s_ease-out]">
        <div className="relative">
          <div className="w-16 h-16 rounded-full bg-emerald-500/15 flex items-center justify-center">
            <svg className="w-8 h-8 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          </div>
          <div
            className="absolute inset-0 rounded-full animate-ping"
            style={{ background: 'rgba(16,185,129,0.15)', animationDuration: '2s', animationIterationCount: '3' }}
          />
        </div>

        <h2 className="text-xl font-bold text-white">Payment confirmed</h2>
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold text-emerald-400">
            {intent.amountLabel} {intent.currency}
          </span>
          <ChainBadge label={chainName(chainId, intent.chainLabel)} variant="success" />
        </div>

        {link && txHash && (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-300 transition-colors"
          >
            <span className="font-mono">{txHash.slice(0, 10)}...{txHash.slice(-8)}</span>
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
            </svg>
          </a>
        )}

        <p className="text-sm text-zinc-500 mt-1">You can close this page.</p>
      </div>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Shared Components
// ═══════════════════════════════════════════════════════════════

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-2xl p-6 sm:p-8 animate-[fadeIn_0.3s_ease-out]"
      style={{
        background: 'linear-gradient(145deg, rgba(18,18,18,0.95) 0%, rgba(12,12,12,0.98) 100%)',
        border: '1px solid rgba(10,10,10,0.08)',
        boxShadow: '0 25px 50px rgba(0,0,0,0.5)',
      }}
    >
      {children}
    </div>
  )
}

function ChainBadge({
  label,
  variant = 'default',
}: {
  label: string
  variant?: 'default' | 'success' | 'muted'
}) {
  const colors = {
    default: { bg: 'rgba(59,130,246,0.1)', color: '#60a5fa' },
    success: { bg: 'rgba(16,185,129,0.1)', color: '#34d399' },
    muted:   { bg: 'rgba(113,113,122,0.1)', color: '#71717a' },
  }
  const c = colors[variant]
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: c.bg, color: c.color }}
    >
      {label}
    </span>
  )
}
