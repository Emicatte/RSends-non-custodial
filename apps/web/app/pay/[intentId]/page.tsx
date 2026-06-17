'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import QRCodeLib from 'qrcode'
import { requireEnv } from '@/lib/env'

// ═══════════════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════════════

interface PaymentIntent {
  intent_id: string
  reference_id: string
  deposit_address: string | null
  amount: number
  currency: string
  chain: string
  status: string
  metadata: Record<string, unknown> | null
  matched_tx_hash: string | null
  tx_hash: string | null
  expires_at: string
  created_at: string
  completed_at: string | null
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
const EXPLORER_BASE: Record<string, string> = {
  BASE: 'https://basescan.org/tx/',
  ETH: 'https://etherscan.io/tx/',
  ARBITRUM: 'https://arbiscan.io/tx/',
  OPTIMISM: 'https://optimistic.etherscan.io/tx/',
  POLYGON: 'https://polygonscan.com/tx/',
  BSC: 'https://bscscan.com/tx/',
  AVALANCHE: 'https://snowtrace.io/tx/',
  BASE_SEPOLIA: 'https://sepolia.basescan.org/tx/',
  SEPOLIA: 'https://sepolia.etherscan.io/tx/',
}

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

function explorerLink(chain: string, hash: string): string {
  const base = EXPLORER_BASE[chain.toUpperCase()] || EXPLORER_BASE.BASE
  return `${base}${hash}`
}

const CHAIN_IDS: Record<string, number> = {
  BASE: 8453, ETH: 1, ARBITRUM: 42161, OPTIMISM: 10,
  POLYGON: 137, BSC: 56, AVALANCHE: 43114,
  BASE_SEPOLIA: 84532, SEPOLIA: 11155111,
}

const TOKEN_CONTRACTS: Record<string, Record<string, string>> = {
  USDC: {
    BASE: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    ETH: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
    ARBITRUM: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    POLYGON: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359',
  },
  USDT: {
    ETH: '0xdAC17F958D2ee523a2206206994597C13D831ec7',
    ARBITRUM: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
    BSC: '0x55d398326f99059fF775485246999027B3197955',
  },
  DAI: {
    ETH: '0x6B175474E89094C44Da98b954EedeAC495271d0F',
    BASE: '0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb',
  },
}

const TOKEN_DECIMALS: Record<string, number> = {
  ETH: 18, USDC: 6, USDT: 6, DAI: 18, cbBTC: 8, DEGEN: 18,
}

/**
 * Builds EIP-681 payment URI.
 * Native: ethereum:0xADDR@CHAIN_ID?value=AMOUNT_WEI
 * ERC-20: ethereum:0xTOKEN@CHAIN_ID/transfer?address=0xADDR&uint256=AMOUNT_UNITS
 */
function buildEip681Uri(address: string, chain: string, currency: string, amount: number): string {
  const chainId = CHAIN_IDS[chain.toUpperCase()] || 8453
  const isNative = currency.toUpperCase() === 'ETH'
  const decimals = TOKEN_DECIMALS[currency.toUpperCase()] ?? 18

  if (isNative) {
    const weiStr = BigInt(Math.round(amount * 10 ** decimals)).toString()
    return `ethereum:${address}@${chainId}?value=${weiStr}`
  }

  // ERC-20 transfer
  const tokenAddr = TOKEN_CONTRACTS[currency.toUpperCase()]?.[chain.toUpperCase()]
  if (tokenAddr) {
    const units = BigInt(Math.round(amount * 10 ** decimals)).toString()
    return `ethereum:${tokenAddr}@${chainId}/transfer?address=${address}&uint256=${units}`
  }

  // Fallback: plain address with chain
  return `ethereum:${address}@${chainId}`
}

/**
 * QR Code component — generates SVG inline via qrcode library.
 * No external API calls.
 */
function QRCode({ data, className }: { data: string; className?: string }) {
  const [svg, setSvg] = useState<string>('')

  useEffect(() => {
    QRCodeLib.toString(data, {
      type: 'svg',
      margin: 1,
      width: 250,
      color: { dark: '#ffffffFF', light: '#00000000' },
      errorCorrectionLevel: 'M',
    }).then(setSvg).catch(() => setSvg(''))
  }, [data])

  if (!svg) return <div className={className} />

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

function merchantName(meta: Record<string, unknown> | null): string {
  if (!meta) return 'RSends Payment'
  return (meta.merchant_name as string) || (meta.store_name as string) || 'RSends Payment'
}

// ═══════════════════════════════════════════════════════════════
//  WebSocket Hook — real-time payment updates with polling fallback
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
          if (data.event === 'payment.completed' || data.event === 'payment.expired') {
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
        // Attempt reconnect
        if (reconnectsRef.current < WS_MAX_RECONNECTS) {
          reconnectsRef.current += 1
          setTimeout(connect, WS_RECONNECT_DELAY)
        }
      }

      ws.onerror = () => {
        // onclose will fire after onerror — fallback handled there
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
//  Page Component
// ═══════════════════════════════════════════════════════════════

export default function CheckoutPage() {
  const params = useParams<{ intentId: string }>()
  const intentId = params.intentId

  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [copied, setCopied] = useState(false)
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
      const data: PaymentIntent = await res.json()
      setState({ kind: 'ready', intent: data })
      return data
    } catch {
      setState({ kind: 'error', message: 'Network error. Please try again.' })
      return null
    }
  }, [intentId])

  // ── Initial load ─────────────────────────────────────────
  useEffect(() => {
    fetchIntent()
  }, [fetchIntent])

  // ── WebSocket — real-time updates ────────────────────────
  const currentStatus = state.kind === 'ready' ? state.intent.status : null

  const handleWsEvent = useCallback((event: { event: string; tx_hash?: string }) => {
    if (event.event === 'payment.completed') {
      // Immediate UI update, then fetch full intent for tx_hash etc.
      fetchIntent()
    } else if (event.event === 'payment.expired') {
      fetchIntent()
    }
  }, [fetchIntent])

  const connectionMode = usePaymentWebSocket(intentId, currentStatus, handleWsEvent)

  // ── Polling — fallback when WebSocket is not connected ───
  useEffect(() => {
    if (state.kind !== 'ready') return
    const { status } = state.intent

    // Track status transitions
    if (prevStatus && prevStatus !== status) {
      setPrevStatus(status)
    } else if (!prevStatus) {
      setPrevStatus(status)
    }

    // Only poll while pending
    if (status !== 'pending') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    // If WebSocket is live, skip polling
    if (connectionMode === 'live') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    pollRef.current = setInterval(fetchIntent, POLL_INTERVAL)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [state, fetchIntent, prevStatus, connectionMode])

  // ── Copy to clipboard ────────────────────────────────────
  const copyAddress = useCallback((addr: string) => {
    navigator.clipboard.writeText(addr).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }, [])

  // ── Render ───────────────────────────────────────────────
  if (state.kind === 'loading') return <Shell><LoadingView /></Shell>
  if (state.kind === 'not_found') return <Shell><NotFoundView /></Shell>
  if (state.kind === 'error') return <Shell><ErrorView message={state.message} /></Shell>

  const { intent } = state
  const s = intent.status

  if (s === 'expired' || s === 'cancelled')
    return <Shell><ExpiredView intent={intent} /></Shell>

  if (s === 'completed')
    return <Shell><CompletedView intent={intent} /></Shell>

  return (
    <Shell>
      <PendingView
        intent={intent}
        copied={copied}
        onCopy={copyAddress}
        connectionMode={connectionMode}
      />
    </Shell>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Shell
// ═══════════════════════════════════════════════════════════════

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ background: '#0a0a0a' }}
    >
      <div className="w-full max-w-lg">{children}</div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Loading
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  Not Found
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  Error
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  Expired
// ═══════════════════════════════════════════════════════════════

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
            {intent.amount} {intent.currency}
          </span>
          <ChainBadge chain={intent.chain} variant="muted" />
        </div>
      </div>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Completed
// ═══════════════════════════════════════════════════════════════

function CompletedView({ intent }: { intent: PaymentIntent }) {
  const txHash = intent.matched_tx_hash || intent.tx_hash
  const link = txHash ? explorerLink(intent.chain, txHash) : null

  return (
    <Card>
      <div className="flex flex-col items-center gap-4 py-8 animate-[fadeScale_0.5s_ease-out]">
        {/* Checkmark */}
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
            {intent.amount} {intent.currency}
          </span>
          <ChainBadge chain={intent.chain} variant="success" />
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

        <p className="text-sm text-zinc-500 mt-1">
          You can close this page.
        </p>
      </div>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
//  Pending (Main Checkout UI)
// ═══════════════════════════════════════════════════════════════

function PendingView({
  intent,
  copied,
  onCopy,
  connectionMode,
}: {
  intent: PaymentIntent
  copied: boolean
  onCopy: (addr: string) => void
  connectionMode: ConnectionMode
}) {
  const [remaining, setRemaining] = useState('')
  const [expired, setExpired] = useState(false)

  // Countdown timer
  useEffect(() => {
    function tick() {
      const diff = new Date(intent.expires_at).getTime() - Date.now()
      if (diff <= 0) {
        setExpired(true)
        setRemaining('0:00')
        return
      }
      setRemaining(formatCountdown(diff))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [intent.expires_at])

  const addr = intent.deposit_address
  const name = merchantName(intent.metadata)

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
          {intent.amount} {intent.currency}
        </p>
        <div className="mt-2 flex items-center justify-center gap-2">
          <ChainBadge chain={intent.chain} variant="default" />
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

      {/* Divider */}
      <div className="border-t border-white/[0.06] my-5" />

      {/* QR + Address */}
      {addr ? (
        <div className="flex flex-col items-center gap-4">
          {/* QR Code — generated locally, no external API */}
          <div
            className="rounded-xl p-3"
            style={{ background: 'rgba(10,10,10,0.03)', border: '1px solid rgba(10,10,10,0.08)' }}
          >
            <QRCode
              data={buildEip681Uri(addr, intent.chain, intent.currency, intent.amount)}
              className="w-[200px] h-[200px] sm:w-[250px] sm:h-[250px] [&_svg]:w-full [&_svg]:h-full"
            />
          </div>

          {/* Address */}
          <div className="w-full">
            <p className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1.5 text-center">
              Deposit Address
            </p>
            <button
              onClick={() => onCopy(addr)}
              className="w-full group relative rounded-xl px-3 py-2.5 text-left transition-all"
              style={{
                background: 'rgba(10,10,10,0.03)',
                border: '1px solid rgba(10,10,10,0.08)',
              }}
            >
              <span className="block font-mono text-[11px] text-zinc-300 break-all leading-relaxed">
                {addr}
              </span>
              <span
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] font-semibold uppercase tracking-wide transition-all"
                style={{ color: copied ? '#10b981' : '#71717a' }}
              >
                {copied ? 'Copied!' : 'Copy'}
              </span>
            </button>
          </div>

          {/* Instruction */}
          <p className="text-sm text-zinc-400 text-center">
            Send exactly <span className="text-white font-semibold">{intent.amount} {intent.currency}</span> to this address
          </p>
        </div>
      ) : (
        <div className="text-center py-6">
          <p className="text-sm text-zinc-500">
            Deposit address not available. Contact the merchant.
          </p>
        </div>
      )}

      {/* Divider */}
      <div className="border-t border-white/[0.06] my-5" />

      {/* Waiting indicator with connection status */}
      <div className="flex items-center justify-center gap-2">
        <span
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ background: connectionMode === 'live' ? '#22c55e' : '#eab308' }}
        />
        <span className="text-xs text-zinc-500">
          Waiting for payment...
        </span>
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

      {/* Footer */}
      <p className="text-center text-[10px] text-zinc-600 mt-4">
        Payment will be confirmed automatically
      </p>
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
  chain,
  variant = 'default',
}: {
  chain: string
  variant?: 'default' | 'success' | 'muted'
}) {
  const label = CHAIN_LABELS[chain.toUpperCase()] || chain
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
