'use client'

import { useState, useEffect, useCallback, useRef, Fragment } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import QRCodeLib from 'qrcode'

// ═══════════════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════════════

type Tab = 'overview' | 'intents' | 'webhooks' | 'keys'

interface Intent {
  intent_id: string
  amount: number
  currency: string
  chain: string
  status: string
  deposit_address?: string | null
  tx_hash?: string | null
  matched_tx_hash?: string | null
  metadata?: Record<string, unknown> | null
  reference_id?: string
  created_at: string
  expires_at: string
  completed_at?: string | null
}

interface TxListResponse {
  total: number
  page: number
  per_page: number
  records: Intent[]
}

interface Webhook {
  webhook_id: number
  url: string
  secret?: string
  events: string[]
  is_active: boolean
}

interface Delivery {
  id: number
  event_type: string
  status: string
  response_code?: number | null
  next_retry_at?: string | null
  created_at: string
}

// ═══════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'overview',  label: 'Overview',  icon: '📊' },
  { key: 'intents',   label: 'Intents',   icon: '💳' },
  { key: 'webhooks',  label: 'Webhooks',  icon: '🔔' },
  { key: 'keys',      label: 'API Keys',  icon: '🔑' },
]

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  pending:   'bg-amber-500/20 text-amber-400 border-amber-500/30',
  expired:   'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  cancelled: 'bg-red-500/20 text-red-400 border-red-500/30',
  review:    'bg-purple-500/20 text-purple-400 border-purple-500/30',
  partial:   'bg-orange-500/20 text-orange-400 border-orange-500/30',
  overpaid:  'bg-blue-500/20 text-blue-400 border-blue-500/30',
  failed:    'bg-red-500/20 text-red-400 border-red-500/30',
  delivered: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
}

const CURRENCY_OPTIONS = ['', 'USDC', 'ETH', 'USDT', 'DAI', 'cbBTC', 'EURC']
const STATUS_OPTIONS = ['', 'pending', 'completed', 'expired', 'cancelled', 'review']
const CHAIN_OPTIONS = ['BASE', 'BASE_SEPOLIA', 'ETH', 'ARBITRUM']
const EXPIRY_OPTIONS = [
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '1 hour', value: 60 },
  { label: '24 hours', value: 1440 },
]

const EXPLORER: Record<string, string> = {
  BASE: 'https://basescan.org/tx/',
  ETH: 'https://etherscan.io/tx/',
  ARBITRUM: 'https://arbiscan.io/tx/',
  BASE_SEPOLIA: 'https://sepolia.basescan.org/tx/',
}

// ═══════════════════════════════════════════════════════════════
//  API helpers
// ═══════════════════════════════════════════════════════════════

function getApiKey(): string | null {
  if (typeof window === 'undefined') return null
  return sessionStorage.getItem('merchant_api_key')
}

function setApiKey(key: string) {
  sessionStorage.setItem('merchant_api_key', key)
}

function clearApiKey() {
  sessionStorage.removeItem('merchant_api_key')
}

async function api<T = unknown>(
  path: string,
  opts: RequestInit = {},
): Promise<{ ok: boolean; status: number; data: T }> {
  const key = getApiKey()
  const res = await fetch(`/api/merchant/${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
      ...(opts.headers || {}),
    },
  })
  const data = await res.json()
  return { ok: res.ok, status: res.status, data }
}

// ═══════════════════════════════════════════════════════════════
//  Shared micro-components
// ═══════════════════════════════════════════════════════════════

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || 'bg-zinc-700/40 text-zinc-300 border-zinc-600/30'
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded-full border ${c}`}>
      {status}
    </span>
  )
}

function DashQR({ data, size = 160 }: { data: string; size?: number }) {
  const [svg, setSvg] = useState('')
  useEffect(() => {
    QRCodeLib.toString(data, {
      type: 'svg', margin: 1, width: size,
      color: { dark: '#00ffa3FF', light: '#00000000' },
      errorCorrectionLevel: 'M',
    }).then(setSvg).catch(() => setSvg(''))
  }, [data, size])
  if (!svg) return null
  return <div style={{ width: size, height: size }} dangerouslySetInnerHTML={{ __html: svg }} />
}

function Card({ children, className = '', onClick }: { children: React.ReactNode; className?: string; onClick?: (e: React.MouseEvent) => void }) {
  return (
    <div className={`bg-zinc-900/60 border border-zinc-800 rounded-xl p-5 ${className}`} onClick={onClick}>
      {children}
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <Card>
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-zinc-400 mt-1">{sub}</p>}
    </Card>
  )
}

function Btn({
  children, onClick, variant = 'primary', disabled = false, className = '',
}: {
  children: React.ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  disabled?: boolean
  className?: string
}) {
  const base = 'px-4 py-2 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40'
  const v: Record<string, string> = {
    primary:   'bg-blue-600 hover:bg-blue-500 text-white',
    secondary: 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700',
    danger:    'bg-red-600/20 hover:bg-red-600/40 text-red-400 border border-red-600/30',
    ghost:     'bg-transparent hover:bg-zinc-800 text-zinc-400',
  }
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${v[variant]} ${className}`}>
      {children}
    </button>
  )
}

function Spinner() {
  return (
    <div className="inline-block w-4 h-4 border-2 border-zinc-600 border-t-blue-500 rounded-full animate-spin" />
  )
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function truncHash(h?: string | null) {
  if (!h) return '—'
  return `${h.slice(0, 8)}...${h.slice(-6)}`
}

// ═══════════════════════════════════════════════════════════════
//  LOGIN SCREEN
// ═══════════════════════════════════════════════════════════════

function LoginScreen({ onLogin }: { onLogin: (key: string) => void }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    if (!key.trim()) return
    setLoading(true)
    setError('')
    setApiKey(key.trim())
    const res = await api<TxListResponse>('transactions?page=1&per_page=1')
    setLoading(false)
    if (res.status === 401 || res.status === 403) {
      clearApiKey()
      setError('Invalid API key')
      return
    }
    if (!res.ok) {
      clearApiKey()
      setError(`Error: ${(res.data as { message?: string })?.message || res.status}`)
      return
    }
    onLogin(key.trim())
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-white mb-1">Merchant Dashboard</h1>
        <p className="text-sm text-zinc-400 mb-6">Enter your API key to continue</p>

        <input
          type="password"
          value={key}
          onChange={e => setKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="Bearer API key"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none mb-3"
        />

        {error && <p className="text-sm text-red-400 mb-3">{error}</p>}

        <Btn onClick={submit} disabled={loading || !key.trim()} className="w-full">
          {loading ? <Spinner /> : 'Sign In'}
        </Btn>
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  TAB 1 — OVERVIEW
// ═══════════════════════════════════════════════════════════════

function OverviewTab() {
  const [txs, setTxs] = useState<Intent[]>([])
  const [stats, setStats] = useState({ total: 0, completed: 0, pending: 0, volume: 0 })
  const [chartData, setChartData] = useState<{ day: string; volume: number }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const res = await api<TxListResponse>('transactions?page=1&per_page=200')
      if (cancelled || !res.ok) { setLoading(false); return }
      const records = res.data.records || []
      setTxs(records.slice(0, 5))

      let completed = 0, pending = 0, vol = 0
      const dayMap: Record<string, number> = {}

      for (const r of records) {
        if (r.status === 'completed' || r.status === 'overpaid') { completed++; vol += r.amount }
        if (r.status === 'pending') pending++
        const day = r.created_at.slice(0, 10)
        if (r.status === 'completed' || r.status === 'overpaid') {
          dayMap[day] = (dayMap[day] || 0) + r.amount
        }
      }

      setStats({ total: records.length, completed, pending, volume: vol })

      const days = Object.entries(dayMap)
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(-7)
        .map(([day, volume]) => ({ day: day.slice(5), volume: Math.round(volume * 100) / 100 }))
      setChartData(days)
      setLoading(false)
    })()
    return () => { cancelled = true }
  }, [])

  if (loading) return <div className="flex items-center gap-2 text-zinc-400 py-12 justify-center"><Spinner /> Loading...</div>

  return (
    <div className="space-y-6">
      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Payments" value={stats.total} />
        <StatCard label="Completed" value={stats.completed} />
        <StatCard label="Pending" value={stats.pending} />
        <StatCard label="Total Volume" value={`$${stats.volume.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-zinc-300 mb-4">Daily Volume (last 7 days)</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="day" tick={{ fill: '#71717a', fontSize: 12 }} />
              <YAxis tick={{ fill: '#71717a', fontSize: 12 }} />
              <Tooltip
                contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 8, fontSize: 13 }}
                labelStyle={{ color: '#a1a1aa' }}
              />
              <Bar dataKey="volume" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* Recent Transactions */}
      <Card>
        <h3 className="text-sm font-semibold text-zinc-300 mb-3">Recent Transactions</h3>
        {txs.length === 0 ? (
          <p className="text-sm text-zinc-500 py-4 text-center">No transactions yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-xs uppercase border-b border-zinc-800">
                  <th className="text-left py-2 pr-4">ID</th>
                  <th className="text-right py-2 pr-4">Amount</th>
                  <th className="text-left py-2 pr-4">Status</th>
                  <th className="text-left py-2 hidden sm:table-cell">Created</th>
                </tr>
              </thead>
              <tbody>
                {txs.map(tx => (
                  <tr key={tx.intent_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-2.5 pr-4 font-mono text-xs text-zinc-300">{tx.intent_id.slice(0, 14)}...</td>
                    <td className="py-2.5 pr-4 text-right text-white">{tx.amount} {tx.currency}</td>
                    <td className="py-2.5 pr-4"><StatusBadge status={tx.status} /></td>
                    <td className="py-2.5 text-zinc-400 text-xs hidden sm:table-cell">{fmtDate(tx.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  TAB 2 — PAYMENT INTENTS
// ═══════════════════════════════════════════════════════════════

function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: (i: Intent) => void }) {
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('USDC')
  const [chain, setChain] = useState('BASE')
  const [expiry, setExpiry] = useState(30)
  const [meta, setMeta] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Intent | null>(null)
  const [copied, setCopied] = useState('')

  const submit = async () => {
    setError('')
    const amt = parseFloat(amount)
    if (!amt || amt <= 0) { setError('Amount must be > 0'); return }

    let metadata: Record<string, unknown> | undefined
    if (meta.trim()) {
      try { metadata = JSON.parse(meta) }
      catch { setError('Invalid JSON in metadata'); return }
    }

    setLoading(true)
    const res = await api<Intent>('payment-intent', {
      method: 'POST',
      body: JSON.stringify({
        amount: amt, currency, chain,
        expires_in_minutes: expiry,
        ...(metadata ? { metadata } : {}),
      }),
    })
    setLoading(false)

    if (!res.ok) {
      setError((res.data as { detail?: string })?.detail || 'Failed to create intent')
      return
    }
    setResult(res.data)
    onCreated(res.data)
  }

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    setCopied(label)
    setTimeout(() => setCopied(''), 2000)
  }

  const payLink = result ? `${typeof window !== 'undefined' ? window.location.origin : ''}/pay/${result.intent_id}` : ''

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <Card className="w-full max-w-lg max-h-[90vh] overflow-y-auto" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
        {!result ? (
          <>
            <h2 className="text-lg font-bold text-white mb-4">Create Payment Intent</h2>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-zinc-500 block mb-1">Amount</label>
                <input type="number" step="0.01" min="0" value={amount} onChange={e => setAmount(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-zinc-500 block mb-1">Currency</label>
                  <select value={currency} onChange={e => setCurrency(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
                    <option>USDC</option><option>ETH</option><option>USDT</option><option>DAI</option><option>cbBTC</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-zinc-500 block mb-1">Chain</label>
                  <select value={chain} onChange={e => setChain(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
                    {CHAIN_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-zinc-500 block mb-1">Expiration</label>
                  <select value={expiry} onChange={e => setExpiry(Number(e.target.value))}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
                    {EXPIRY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="text-xs text-zinc-500 block mb-1">Metadata (optional JSON)</label>
                <textarea value={meta} onChange={e => setMeta(e.target.value)} rows={3}
                  placeholder='{"order_id": "ORD-123"}'
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none resize-none" />
              </div>
            </div>

            {error && <p className="text-sm text-red-400 mt-3">{error}</p>}

            <div className="flex gap-3 mt-5">
              <Btn onClick={submit} disabled={loading} className="flex-1">
                {loading ? <><Spinner />{' '}Creating...</> : 'Create Intent'}
              </Btn>
              <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-lg font-bold text-white mb-4">Payment Intent Created</h2>

            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">Intent ID</span>
                <span className="text-white font-mono text-xs">{result.intent_id}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">Amount</span>
                <span className="text-white">{result.amount} {result.currency}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-400">Chain</span>
                <span className="text-white">{result.chain}</span>
              </div>

              {result.deposit_address && (
                <div>
                  <p className="text-xs text-zinc-500 mb-1">Deposit Address</p>
                  <div className="flex items-center gap-2 bg-zinc-800 rounded-lg p-2.5">
                    <code className="text-xs text-emerald-400 flex-1 break-all">{result.deposit_address}</code>
                    <button onClick={() => copyText(result.deposit_address!, 'addr')}
                      className="text-xs text-zinc-400 hover:text-white shrink-0">
                      {copied === 'addr' ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
              )}

              {result.deposit_address && (
                <div className="flex justify-center py-2">
                  <DashQR data={result.deposit_address} />
                </div>
              )}

              <div>
                <p className="text-xs text-zinc-500 mb-1">Payment Link</p>
                <div className="flex items-center gap-2 bg-zinc-800 rounded-lg p-2.5">
                  <code className="text-xs text-blue-400 flex-1 break-all">{payLink}</code>
                  <button onClick={() => copyText(payLink, 'link')}
                    className="text-xs text-zinc-400 hover:text-white shrink-0">
                    {copied === 'link' ? 'Copied!' : 'Copy'}
                  </button>
                </div>
              </div>
            </div>

            <Btn onClick={onClose} className="w-full mt-5">Done</Btn>
          </>
        )}
      </Card>
    </div>
  )
}

function IntentsTab() {
  const [intents, setIntents] = useState<Intent[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterCurrency, setFilterCurrency] = useState('')
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const perPage = 15

  const load = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
    if (filterStatus) params.set('status', filterStatus)
    if (filterCurrency) params.set('currency', filterCurrency)
    const res = await api<TxListResponse>(`transactions?${params}`)
    if (res.ok) {
      setIntents(res.data.records || [])
      setTotal(res.data.total || 0)
    }
    setLoading(false)
  }, [page, filterStatus, filterCurrency])

  useEffect(() => { load() }, [load])

  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <select value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.filter(Boolean).map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        <select value={filterCurrency} onChange={e => { setFilterCurrency(e.target.value); setPage(1) }}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
          <option value="">All Currencies</option>
          {CURRENCY_OPTIONS.filter(Boolean).map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        <div className="flex-1" />

        <Btn onClick={() => setShowCreate(true)}>+ Create Intent</Btn>
      </div>

      {/* Table */}
      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center gap-2 text-zinc-400 py-12 justify-center"><Spinner /> Loading...</div>
        ) : intents.length === 0 ? (
          <p className="text-sm text-zinc-500 py-12 text-center">No payment intents found</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-xs uppercase border-b border-zinc-800 bg-zinc-900/40">
                  <th className="text-left py-3 px-4">Intent ID</th>
                  <th className="text-right py-3 px-4">Amount</th>
                  <th className="text-left py-3 px-4">Currency</th>
                  <th className="text-left py-3 px-4 hidden md:table-cell">Chain</th>
                  <th className="text-left py-3 px-4">Status</th>
                  <th className="text-left py-3 px-4 hidden lg:table-cell">Created</th>
                  <th className="text-left py-3 px-4 hidden lg:table-cell">Expires</th>
                  <th className="text-left py-3 px-4 hidden xl:table-cell">TX Hash</th>
                </tr>
              </thead>
              <tbody>
                {intents.map(i => (
                  <tr key={i.intent_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                    <td className="py-3 px-4 font-mono text-xs text-zinc-300">{i.intent_id.slice(0, 16)}...</td>
                    <td className="py-3 px-4 text-right text-white font-medium">{i.amount}</td>
                    <td className="py-3 px-4 text-zinc-300">{i.currency}</td>
                    <td className="py-3 px-4 text-zinc-400 hidden md:table-cell">{i.chain}</td>
                    <td className="py-3 px-4"><StatusBadge status={i.status} /></td>
                    <td className="py-3 px-4 text-zinc-400 text-xs hidden lg:table-cell">{fmtDate(i.created_at)}</td>
                    <td className="py-3 px-4 text-zinc-400 text-xs hidden lg:table-cell">{fmtDate(i.expires_at)}</td>
                    <td className="py-3 px-4 hidden xl:table-cell">
                      {(i.matched_tx_hash || i.tx_hash) ? (
                        <a href={`${EXPLORER[i.chain] || EXPLORER.BASE}${i.matched_tx_hash || i.tx_hash}`}
                          target="_blank" rel="noopener noreferrer"
                          className="font-mono text-xs text-blue-400 hover:underline">
                          {truncHash(i.matched_tx_hash || i.tx_hash)}
                        </a>
                      ) : <span className="text-zinc-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-800">
            <span className="text-xs text-zinc-500">{total} total</span>
            <div className="flex gap-1">
              <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>&larr;</Btn>
              <span className="px-3 py-2 text-xs text-zinc-400">{page} / {totalPages}</span>
              <Btn variant="ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>&rarr;</Btn>
            </div>
          </div>
        )}
      </Card>

      {showCreate && (
        <CreateIntentModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { load() }}
        />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  TAB 3 — WEBHOOKS
// ═══════════════════════════════════════════════════════════════

function WebhooksTab() {
  const [webhook, setWebhook] = useState<Webhook | null>(null)
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState('payment.completed,payment.expired')
  const [regLoading, setRegLoading] = useState(false)
  const [regError, setRegError] = useState('')
  const [testLoading, setTestLoading] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [showSecret, setShowSecret] = useState(false)
  const [loading, setLoading] = useState(true)

  // We don't have a GET /webhooks endpoint, so we try to show the registered one from sessionStorage
  useEffect(() => {
    const saved = sessionStorage.getItem('merchant_webhook')
    if (saved) {
      try { setWebhook(JSON.parse(saved)) } catch {}
    }
    setLoading(false)
  }, [])

  const register = async () => {
    if (!url.trim()) return
    if (!url.trim().startsWith('https://')) {
      setRegError('Webhook URL must start with https://')
      return
    }
    setRegLoading(true)
    setRegError('')
    const evList = events.split(',').map(e => e.trim()).filter(Boolean)
    const res = await api<Webhook>('webhook/register', {
      method: 'POST',
      body: JSON.stringify({ url: url.trim(), events: evList }),
    })
    setRegLoading(false)
    if (!res.ok) {
      setRegError((res.data as { detail?: string })?.detail || 'Registration failed')
      return
    }
    setWebhook(res.data)
    sessionStorage.setItem('merchant_webhook', JSON.stringify(res.data))
  }

  const sendTest = async () => {
    if (!webhook) return
    setTestLoading(true)
    setTestResult(null)
    const res = await api<{ status: string; response_code?: number; message: string }>('webhook/test', {
      method: 'POST',
      body: JSON.stringify({ webhook_id: webhook.webhook_id }),
    })
    setTestLoading(false)
    setTestResult({
      ok: res.ok && res.data.status === 'ok',
      msg: res.data.message || (res.ok ? 'Sent' : 'Failed'),
    })
  }

  if (loading) return <div className="flex items-center gap-2 text-zinc-400 py-12 justify-center"><Spinner /></div>

  return (
    <div className="space-y-6">
      {webhook ? (
        <>
          <Card>
            <h3 className="text-sm font-semibold text-zinc-300 mb-4">Registered Webhook</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-zinc-500">URL</span>
                <span className="text-white font-mono text-xs break-all max-w-[70%] text-right">{webhook.url}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Events</span>
                <span className="text-zinc-300 text-xs">{webhook.events.join(', ')}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-zinc-500">Secret</span>
                <div className="flex items-center gap-2">
                  <code className="text-xs text-amber-400 font-mono">
                    {showSecret ? webhook.secret : '••••••••••••••••'}
                  </code>
                  {webhook.secret && (
                    <button onClick={() => setShowSecret(!showSecret)}
                      className="text-xs text-zinc-500 hover:text-zinc-300">
                      {showSecret ? 'Hide' : 'Show'}
                    </button>
                  )}
                </div>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Status</span>
                <StatusBadge status={webhook.is_active ? 'completed' : 'expired'} />
              </div>
            </div>

            <div className="flex gap-3 mt-5">
              <Btn onClick={sendTest} disabled={testLoading} variant="secondary">
                {testLoading ? <><Spinner /> Sending...</> : 'Send Test Event'}
              </Btn>
            </div>

            {testResult && (
              <div className={`mt-3 text-sm px-3 py-2 rounded-lg ${testResult.ok ? 'bg-emerald-900/30 text-emerald-400' : 'bg-red-900/30 text-red-400'}`}>
                {testResult.msg}
              </div>
            )}
          </Card>
        </>
      ) : (
        <Card>
          <h3 className="text-sm font-semibold text-zinc-300 mb-4">Register Webhook</h3>

          <div className="space-y-3">
            <div>
              <label className="text-xs text-zinc-500 block mb-1">Webhook URL (HTTPS)</label>
              <input value={url} onChange={e => setUrl(e.target.value)}
                placeholder="https://your-server.com/webhook"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
            </div>
            <div>
              <label className="text-xs text-zinc-500 block mb-1">Events (comma-separated)</label>
              <input value={events} onChange={e => setEvents(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none" />
            </div>
          </div>

          {regError && <p className="text-sm text-red-400 mt-3">{regError}</p>}

          <Btn onClick={register} disabled={regLoading || !url.trim()} className="mt-4">
            {regLoading ? <><Spinner /> Registering...</> : 'Register Webhook'}
          </Btn>
        </Card>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  TAB 4 — API KEYS
// ═══════════════════════════════════════════════════════════════

function KeysTab({ onLogout }: { onLogout: () => void }) {
  const key = getApiKey() || ''
  const masked = key.length > 8 ? `${'•'.repeat(key.length - 8)}${key.slice(-8)}` : key
  const [copied, setCopied] = useState(false)

  const curlSnippet = `curl -X POST ${typeof window !== 'undefined' ? window.location.origin : ''}/api/merchant/payment-intent \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": 10.00,
    "currency": "USDC",
    "chain": "BASE",
    "expires_in_minutes": 30,
    "metadata": {"order_id": "ORD-123"}
  }'`

  return (
    <div className="space-y-6">
      <Card>
        <h3 className="text-sm font-semibold text-zinc-300 mb-4">Current API Key</h3>
        <div className="flex items-center gap-3 bg-zinc-800 rounded-lg p-3">
          <code className="text-sm text-zinc-300 font-mono flex-1">{masked}</code>
        </div>
        <div className="flex gap-3 mt-4">
          <Btn variant="danger" onClick={() => {
            if (confirm('Are you sure? You will need to re-enter your API key.')) {
              onLogout()
            }
          }}>
            Logout
          </Btn>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-zinc-300 mb-4">Integration Snippet</h3>
        <div className="relative">
          <pre className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 text-xs text-zinc-300 font-mono overflow-x-auto whitespace-pre-wrap">
            {curlSnippet}
          </pre>
          <button
            onClick={() => { navigator.clipboard.writeText(curlSnippet); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            className="absolute top-2 right-2 text-xs text-zinc-500 hover:text-white bg-zinc-800 px-2 py-1 rounded">
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-zinc-300 mb-4">API Reference</h3>
        <div className="space-y-2 text-sm text-zinc-400">
          <div className="flex gap-3">
            <code className="text-xs bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded font-mono">POST</code>
            <span>/api/merchant/payment-intent</span>
          </div>
          <div className="flex gap-3">
            <code className="text-xs bg-blue-900/30 text-blue-400 px-2 py-0.5 rounded font-mono">GET</code>
            <span>/api/merchant/payment-intent/:id</span>
          </div>
          <div className="flex gap-3">
            <code className="text-xs bg-red-900/30 text-red-400 px-2 py-0.5 rounded font-mono">POST</code>
            <span>/api/merchant/payment-intent/:id/cancel</span>
          </div>
          <div className="flex gap-3">
            <code className="text-xs bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded font-mono">POST</code>
            <span>/api/merchant/webhook/register</span>
          </div>
          <div className="flex gap-3">
            <code className="text-xs bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded font-mono">POST</code>
            <span>/api/merchant/webhook/test</span>
          </div>
          <div className="flex gap-3">
            <code className="text-xs bg-blue-900/30 text-blue-400 px-2 py-0.5 rounded font-mono">GET</code>
            <span>/api/merchant/transactions?page=1&per_page=25</span>
          </div>
        </div>
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
//  MAIN DASHBOARD
// ═══════════════════════════════════════════════════════════════

export default function MerchantDashboardPage() {
  const [authed, setAuthed] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
    if (getApiKey()) setAuthed(true)
  }, [])

  const handleLogin = (key: string) => {
    setApiKey(key)
    setAuthed(true)
  }

  const handleLogout = () => {
    clearApiKey()
    sessionStorage.removeItem('merchant_webhook')
    setAuthed(false)
  }

  // Handle 401 globally
  useEffect(() => {
    if (!authed) return
    const orig = window.fetch
    window.fetch = async (...args) => {
      const res = await orig(...args)
      if (res.status === 401 && typeof args[0] === 'string' && args[0].includes('/api/merchant/')) {
        clearApiKey()
        setAuthed(false)
      }
      return res
    }
    return () => { window.fetch = orig }
  }, [authed])

  if (!mounted) return null
  if (!authed) return <LoginScreen onLogin={handleLogin} />

  const TabContent = {
    overview: <OverviewTab />,
    intents:  <IntentsTab />,
    webhooks: <WebhooksTab />,
    keys:     <KeysTab onLogout={handleLogout} />,
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Desktop layout: sidebar + content */}
      <div className="flex">
        {/* Sidebar — hidden on mobile */}
        <aside className="hidden md:flex flex-col w-56 min-h-screen bg-zinc-900/50 border-r border-zinc-800 p-4 shrink-0">
          <div className="mb-8">
            <h1 className="text-lg font-bold text-white">RPagos</h1>
            <p className="text-xs text-zinc-500">Merchant Dashboard</p>
          </div>

          <nav className="flex-1 space-y-1">
            {TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === t.key
                    ? 'bg-blue-600/20 text-blue-400'
                    : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
                }`}
              >
                <span className="text-base">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>

          <div className="pt-4 border-t border-zinc-800">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-zinc-500 hover:bg-zinc-800 hover:text-red-400 transition-colors"
            >
              Logout
            </button>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-4 md:p-8 pb-20 md:pb-8 min-w-0">
          {/* Mobile Header */}
          <div className="md:hidden mb-6">
            <h1 className="text-lg font-bold text-white">RPagos</h1>
            <p className="text-xs text-zinc-500">Merchant Dashboard</p>
          </div>

          <h2 className="text-xl font-bold text-white mb-6 hidden md:block">
            {TABS.find(t => t.key === activeTab)?.label}
          </h2>

          {TabContent[activeTab]}
        </main>
      </div>

      {/* Mobile bottom tabs */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-zinc-900/95 border-t border-zinc-800 backdrop-blur-lg z-40">
        <div className="flex">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs transition-colors ${
                activeTab === t.key ? 'text-blue-400' : 'text-zinc-500'
              }`}
            >
              <span className="text-lg">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>
      </nav>
    </div>
  )
}
