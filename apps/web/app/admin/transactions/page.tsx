'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'

// ── Types ────────────────────────────────────────────────────────────────────

interface TxRecord {
  tx_hash: string
  gross_amount: number
  net_amount: number
  fee_amount: number
  currency: string
  eur_value: number | null
  status: string
  network: string
  recipient: string | null
  tx_timestamp: string | null
}

interface ApiResponse {
  records: TxRecord[]
  total?: number
  error?: string
}

// ── Auth helpers ─────────────────────────────────────────────────────────────

async function verifySession(): Promise<boolean> {
  try {
    const res = await fetch('/api/admin/verify', { credentials: 'same-origin' })
    return res.ok
  } catch {
    return false
  }
}

async function logout(): Promise<void> {
  await fetch('/api/admin/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {})
}

// ── Format helpers ───────────────────────────────────────────────────────────

function truncate(s: string, len = 6): string {
  if (s.length <= len * 2 + 3) return s
  return `${s.slice(0, len + 2)}\u2026${s.slice(-len)}`
}

function explorerUrl(hash: string, network: string, type: 'tx' | 'address'): string {
  const base = network === 'BASE_MAINNET' || network === 'BASE'
    ? 'https://basescan.org' : network === 'BASE_SEPOLIA'
      ? 'https://sepolia.basescan.org' : 'https://etherscan.io'
  return `${base}/${type}/${hash}`
}

function fmtDate(iso: string | null): string {
  if (!iso) return '\u2014'
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function fmtAmount(n: number | null | undefined): string {
  if (n == null) return '\u2014'
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })
}

function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'ora'
  if (mins < 60) return `${mins}m fa`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h fa`
  return `${Math.floor(hours / 24)}g fa`
}

// ── Badge components ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const m: Record<string, { dot: string; bg: string; text: string }> = {
    completed: { dot: 'bg-emerald-400', bg: 'bg-emerald-500/[0.08]', text: 'text-emerald-400' },
    pending:   { dot: 'bg-amber-400',   bg: 'bg-amber-500/[0.08]',   text: 'text-amber-400' },
    failed:    { dot: 'bg-red-400',      bg: 'bg-red-500/[0.08]',     text: 'text-red-400' },
    cancelled: { dot: 'bg-zinc-500',     bg: 'bg-zinc-500/[0.08]',    text: 'text-zinc-500' },
  }
  const s = m[status] ?? m.cancelled
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider ${s.bg} ${s.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  )
}

function NetworkBadge({ network }: { network: string }) {
  const m: Record<string, { bg: string; border: string; text: string; label: string }> = {
    BASE_MAINNET: { bg: 'bg-blue-500/[0.06]', border: 'border-blue-500/10', text: 'text-blue-400',   label: 'Base' },
    BASE:         { bg: 'bg-blue-500/[0.06]', border: 'border-blue-500/10', text: 'text-blue-400',   label: 'Base' },
    BASE_SEPOLIA: { bg: 'bg-violet-500/[0.06]', border: 'border-violet-500/10', text: 'text-violet-400', label: 'Sepolia' },
    ETHEREUM:     { bg: 'bg-indigo-500/[0.06]', border: 'border-indigo-500/10', text: 'text-indigo-400', label: 'Ethereum' },
  }
  const n = m[network] ?? { bg: 'bg-zinc-500/[0.06]', border: 'border-zinc-500/10', text: 'text-zinc-500', label: network }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[10px] font-semibold uppercase tracking-wider ${n.bg} ${n.border} ${n.text}`}>
      {n.label}
    </span>
  )
}

// ── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ title, value, sub, icon, gradient }: {
  title: string; value: string; sub?: string; icon: React.ReactNode; gradient: string
}) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-black/[0.06] p-5 transition-all hover:border-black/[0.1]"
      style={{ background: 'rgba(255,255,255,0.8)' }}>
      {/* Subtle gradient accent top */}
      <div className="absolute top-0 left-0 right-0 h-[1px] opacity-40" style={{ background: gradient }} />
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-1.5" style={{ color: 'rgba(10,10,10,0.55)' }}>{title}</p>
          <p className="text-2xl font-bold tracking-tight text-[#0A0A0A]">{value}</p>
          {sub && <p className="mt-0.5 text-[11px]" style={{ color: 'rgba(10,10,10,0.55)' }}>{sub}</p>}
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-black/[0.06]"
          style={{ background: 'rgba(10,10,10,0.02)' }}>
          {icon}
        </div>
      </div>
    </div>
  )
}

// ── Icons ────────────────────────────────────────────────────────────────────

const IconTx = () => (
  <svg className="h-4 w-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
  </svg>
)
const IconVolume = () => (
  <svg className="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
  </svg>
)
const IconFee = () => (
  <svg className="h-4 w-4 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" />
  </svg>
)
const IconClock = () => (
  <svg className="h-4 w-4 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
  </svg>
)
const IconRefresh = ({ spin }: { spin: boolean }) => (
  <svg className={`h-3.5 w-3.5 ${spin ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
)

// ── Main ─────────────────────────────────────────────────────────────────────

export default function AdminTransactionsPage() {
  const router = useRouter()
  const [authed, setAuthed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [records, setRecords] = useState<TxRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(20)
  const [fCurrency, setFCurrency] = useState('')
  const [fNetwork, setFNetwork] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [fWallet, setFWallet] = useState('')
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [error, setError] = useState('')
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    verifySession().then(ok => {
      if (ok) setAuthed(true)
      else router.push('/admin/login')
    })
  }, [router])

  const fetchData = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true)
    setError('')
    const p = new URLSearchParams()
    p.set('limit', String(limit)); p.set('page', String(page))
    if (fCurrency) p.set('currency', fCurrency)
    if (fNetwork) p.set('network', fNetwork)
    if (fStatus) p.set('status', fStatus)
    if (fWallet) p.set('wallet', fWallet)
    try {
      const res = await fetch(`/api/admin/transactions?${p}`, {
        credentials: 'same-origin',
      })
      if (res.status === 401) { await logout(); router.push('/admin/login'); return }
      const json: ApiResponse = await res.json()
      if (!res.ok) { setError(json.error ?? `Errore ${res.status}`); return }
      setRecords(json.records ?? [])
      setTotal(json.total ?? json.records?.length ?? 0)
      setLastRefresh(new Date())
    } catch (e) { setError(e instanceof Error ? e.message : 'Errore di rete') }
    finally { setLoading(false) }
  }, [limit, page, fCurrency, fNetwork, fStatus, fWallet, router])

  useEffect(() => {
    if (!authed) return
    fetchData()
    autoRef.current = setInterval(() => fetchData({ silent: true }), 30_000)
    return () => { if (autoRef.current) clearInterval(autoRef.current) }
  }, [authed, fetchData])

  useEffect(() => {
    if (!authed) return
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => { setPage(1); fetchData() }, 300)
    return () => { if (debounce.current) clearTimeout(debounce.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fCurrency, fNetwork, fStatus, fWallet])

  const totalTx = total || records.length
  const totalVolume = records.reduce((s, r) => s + (r.gross_amount ?? 0), 0)
  const totalFees = records.reduce((s, r) => s + (r.fee_amount ?? 0), 0)
  const nowMs = Date.now()
  const tx24h = records.filter(r => r.tx_timestamp && nowMs - new Date(r.tx_timestamp).getTime() < 86_400_000).length
  const totalPages = Math.max(1, Math.ceil(totalTx / limit))

  if (!authed) return null

  const inputCls = 'rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-[#0A0A0A] transition-all focus:border-[#C8512C]/30 focus:outline-none focus:ring-1 focus:ring-[#C8512C]/10 placeholder-black/30'
  const selectCls = `${inputCls} appearance-none cursor-pointer pr-7`

  return (
    <div className="min-h-screen text-[#0A0A0A] antialiased" style={{ background: '#FAFAFA' }}>
      {/* Ambient background */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-20 right-1/3 w-[600px] h-[600px] rounded-full opacity-[0.04]"
          style={{ background: 'radial-gradient(circle, #C8512C 0%, transparent 70%)' }} />
        <div className="absolute bottom-0 left-1/4 w-[400px] h-[400px] rounded-full opacity-[0.03]"
          style={{ background: 'radial-gradient(circle, #C8512C 0%, transparent 70%)' }} />
      </div>

      <div className="relative z-10 mx-auto max-w-[1200px] px-6 py-8">

        {/* ─── Header ─────────────────────────────────────────── */}
        <header className="flex items-center justify-between mb-8 admin-fade-in">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#C8512C]/15"
              style={{ background: 'linear-gradient(135deg, rgba(200,81,44,0.12) 0%, rgba(200,81,44,0.08) 100%)' }}>
              <svg className="h-4.5 w-4.5 text-[#C8512C]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">Transazioni</h1>
              <p className="text-xs flex items-center gap-1.5" style={{ color: 'rgba(10,10,10,0.55)' }}>
                {lastRefresh ? (
                  <>Aggiornato alle {lastRefresh.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</>
                ) : 'Caricamento\u2026'}
                {loading && <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#C8512C]" />}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchData()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3.5 py-2 text-xs font-medium text-zinc-400 hover:text-white hover:bg-white/[0.04] hover:border-white/[0.1] transition-all disabled:opacity-40"
            >
              <IconRefresh spin={loading} />
              Aggiorna
            </button>
            <button
              onClick={() => { logout().then(() => router.push('/admin/login')) }}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3.5 py-2 text-xs font-medium text-zinc-500 hover:text-red-400 hover:border-red-500/15 transition-all"
            >
              Esci
            </button>
          </div>
        </header>

        {/* ─── Stats Grid ─────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="admin-fade-in-1">
            <StatCard title="Transazioni" value={String(totalTx)} sub="totale registrate" icon={<IconTx />}
              gradient="linear-gradient(90deg, transparent, #3b82f6, transparent)" />
          </div>
          <div className="admin-fade-in-2">
            <StatCard title="Volume lordo" value={fmtAmount(totalVolume)} sub="importo totale" icon={<IconVolume />}
              gradient="linear-gradient(90deg, transparent, #10b981, transparent)" />
          </div>
          <div className="admin-fade-in-3">
            <StatCard title="Fee raccolte" value={fmtAmount(totalFees)} sub="commissioni" icon={<IconFee />}
              gradient="linear-gradient(90deg, transparent, #f59e0b, transparent)" />
          </div>
          <div className="admin-fade-in-4">
            <StatCard title="Ultime 24h" value={String(tx24h)} sub="transazioni recenti" icon={<IconClock />}
              gradient="linear-gradient(90deg, transparent, #C8512C, transparent)" />
          </div>
        </div>

        {/* ─── Filters ────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2.5 mb-5 admin-fade-in">
          <div className="relative">
            <select value={fCurrency} onChange={e => setFCurrency(e.target.value)} className={selectCls}>
              <option value="">Tutte le valute</option>
              <option value="ETH">ETH</option>
              <option value="USDC">USDC</option>
              <option value="USDT">USDT</option>
              <option value="EURC">EURC</option>
              <option value="DAI">DAI</option>
              <option value="cbBTC">cbBTC</option>
            </select>
            <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
          <div className="relative">
            <select value={fNetwork} onChange={e => setFNetwork(e.target.value)} className={selectCls}>
              <option value="">Tutti i network</option>
              <option value="BASE_MAINNET">Base</option>
              <option value="BASE_SEPOLIA">Sepolia</option>
              <option value="ETHEREUM">Ethereum</option>
            </select>
            <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
          <div className="relative">
            <select value={fStatus} onChange={e => setFStatus(e.target.value)} className={selectCls}>
              <option value="">Tutti gli status</option>
              <option value="completed">Completed</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
            </select>
            <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
          <input
            type="text" placeholder="Filtra per wallet 0x\u2026" value={fWallet}
            onChange={e => setFWallet(e.target.value)}
            className={`${inputCls} w-full sm:w-52`}
          />
          <div className="ml-auto relative">
            <select value={limit} onChange={e => { setLimit(Number(e.target.value)); setPage(1) }} className={selectCls}>
              <option value={10}>10 / pagina</option>
              <option value={20}>20 / pagina</option>
              <option value={50}>50 / pagina</option>
            </select>
            <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
        </div>

        {/* ─── Error ──────────────────────────────────────────── */}
        {error && (
          <div className="mb-5 flex items-center gap-2 rounded-lg border border-red-500/10 bg-red-500/[0.05] px-4 py-3">
            <svg className="h-4 w-4 flex-shrink-0 text-red-400" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* ─── Table ──────────────────────────────────────────── */}
        <div className="overflow-hidden rounded-xl border border-white/[0.04] admin-fade-in"
          style={{ background: 'rgba(10,10,22,0.6)' }}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.04]" style={{ background: 'rgba(255,255,255,0.01)' }}>
                  {['Data', 'TX Hash', 'Lordo', 'Fee', 'Netto', 'Valuta', 'Network', 'Status', 'Recipient'].map((h, i) => (
                    <th key={h} className={`px-4 py-3 text-[10px] font-bold uppercase tracking-[0.1em] text-zinc-500 ${i >= 2 && i <= 4 ? 'text-right' : 'text-left'}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.length === 0 && !loading && (
                  <tr>
                    <td colSpan={9} className="px-4 py-16 text-center">
                      <div className="mx-auto w-12 h-12 rounded-xl border border-white/[0.04] flex items-center justify-center mb-3"
                        style={{ background: 'rgba(10,10,10,0.04)' }}>
                        <svg className="h-5 w-5 text-zinc-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m6 4.125l2.25 2.25m0 0l2.25 2.25M12 13.875l2.25-2.25M12 13.875l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
                        </svg>
                      </div>
                      <p className="text-sm text-zinc-500 font-medium">Nessuna transazione</p>
                      <p className="text-xs text-zinc-600 mt-1">Le transazioni appariranno qui</p>
                    </td>
                  </tr>
                )}
                {loading && records.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-16 text-center">
                      <svg className="mx-auto h-5 w-5 animate-spin text-blue-400 mb-2" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <p className="text-sm text-zinc-500">Caricamento transazioni...</p>
                    </td>
                  </tr>
                )}
                {records.map((tx, i) => (
                  <tr key={tx.tx_hash + i} className="border-t border-white/[0.03] hover:bg-white/[0.015] transition-colors group">
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="text-xs text-zinc-300">{fmtDate(tx.tx_timestamp)}</div>
                      <div className="text-[10px] text-zinc-600">{timeAgo(tx.tx_timestamp)}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <a href={explorerUrl(tx.tx_hash, tx.network, 'tx')} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 font-mono text-xs text-blue-400/80 hover:text-blue-300 transition-colors">
                        {truncate(tx.tx_hash)}
                        <svg className="h-2.5 w-2.5 opacity-0 group-hover:opacity-50 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                        </svg>
                      </a>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-zinc-200">{fmtAmount(tx.gross_amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-zinc-500">{fmtAmount(tx.fee_amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-zinc-200">{fmtAmount(tx.net_amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className="text-xs font-semibold text-zinc-300">{tx.currency}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3"><NetworkBadge network={tx.network} /></td>
                    <td className="whitespace-nowrap px-4 py-3"><StatusBadge status={tx.status} /></td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {tx.recipient ? (
                        <a href={explorerUrl(tx.recipient, tx.network, 'address')} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 font-mono text-xs text-zinc-400 hover:text-blue-300 transition-colors">
                          {truncate(tx.recipient)}
                          <svg className="h-2.5 w-2.5 opacity-0 group-hover:opacity-50 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                          </svg>
                        </a>
                      ) : <span className="text-zinc-700">{'\u2014'}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ─── Pagination ─────────────────────────────────────── */}
        <div className="mt-4 flex items-center justify-between admin-fade-in">
          <p className="text-xs text-zinc-500">
            Pagina <span className="text-zinc-300 font-medium">{page}</span> di {totalPages}
            <span className="mx-2 text-zinc-700">&middot;</span>
            <span className="text-zinc-300 font-medium">{totalTx}</span> transazioni
          </p>
          <div className="flex items-center gap-1.5">
            <button onClick={() => setPage(1)} disabled={page <= 1}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-xs font-medium text-zinc-500 hover:text-white hover:bg-white/[0.04] transition-all disabled:opacity-20 disabled:cursor-not-allowed">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="m18.75 4.5-7.5 7.5 7.5 7.5m-6-15L5.25 12l7.5 7.5" />
              </svg>
            </button>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white hover:bg-white/[0.04] transition-all disabled:opacity-20 disabled:cursor-not-allowed">
              Prec
            </button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white hover:bg-white/[0.04] transition-all disabled:opacity-20 disabled:cursor-not-allowed">
              Succ
            </button>
            <button onClick={() => setPage(totalPages)} disabled={page >= totalPages}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-xs font-medium text-zinc-500 hover:text-white hover:bg-white/[0.04] transition-all disabled:opacity-20 disabled:cursor-not-allowed">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="m5.25 4.5 7.5 7.5-7.5 7.5m6-15 7.5 7.5-7.5 7.5" />
              </svg>
            </button>
          </div>
        </div>

        {/* ─── Footer ─────────────────────────────────────────── */}
        <div className="mt-8 pt-6 border-t border-white/[0.03] flex items-center justify-between">
          <p className="text-[11px] text-zinc-700">RPagos Admin &middot; Auto-refresh ogni 30s</p>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[11px] text-zinc-600">Live</span>
          </div>
        </div>
      </div>
    </div>
  )
}
