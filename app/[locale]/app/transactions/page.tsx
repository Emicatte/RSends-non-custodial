'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useAccount } from 'wagmi'
import { useWalletAuth } from '@/lib/walletAuth'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  accent: '#C45A3C',
  accentLight: 'rgba(196, 90, 60, 0.08)',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.08)',
}

const CHAIN_BADGE: Record<string, { bg: string; text: string }> = {
  Base: { bg: 'rgba(0, 82, 255, 0.08)', text: '#0052ff' },
  Tron: { bg: 'rgba(255, 6, 10, 0.08)', text: '#cc0510' },
  Sol:  { bg: 'rgba(153, 69, 255, 0.08)', text: '#7c2dc7' },
}

interface SweepLogDTO {
  id: number
  tx_hash: string | null
  amount_usd: number | null
  amount_human: number | null
  token_symbol: string | null
  destination_wallet: string | null
  source_wallet: string | null
  status: string
  created_at: string | null
  executed_at: string | null
  is_split: boolean
}

interface SweepLogsPagination {
  page: number
  per_page: number
  total: number
  pages: number
}

interface SweepLogsResponse {
  logs: SweepLogDTO[]
  pagination: SweepLogsPagination
}

type TxStatus = 'confirmed' | 'pending' | 'failed'

const STATUS_BADGE: Record<TxStatus, { bg: string; text: string }> = {
  confirmed: { bg: COLORS.greenLight, text: COLORS.green },
  pending:   { bg: COLORS.orangeLight, text: COLORS.orange },
  failed:    { bg: COLORS.redLight, text: COLORS.red },
}

type Chain = keyof typeof CHAIN_BADGE
type Token = 'USDC' | 'USDT' | 'ETH' | 'DAI'

type Tx = {
  id: number
  date: string       // YYYY-MM-DD for filter
  dateLabel: string  // displayed format
  hash: string
  type: 'Send' | 'Swap'
  to: string
  amount: string
  token: Token
  chain: Chain
  status: TxStatus
}

const USD_FMT = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const ALLOWED_TOKENS: ReadonlyArray<Token> = ['USDC', 'USDT', 'ETH', 'DAI']
const BE_TO_FE_STATUS: Record<string, TxStatus> = {
  completed: 'confirmed',
  pending: 'pending',
  executing: 'pending',
  failed: 'failed',
  gas_too_high: 'failed',
  skipped: 'failed',
}

const STATUS_OPTIONS: ReadonlyArray<TxStatus | 'all'> = ['all', 'confirmed', 'pending', 'failed']
const CHAIN_OPTIONS: ReadonlyArray<{ value: Chain | 'all'; label: string }> = [
  { value: 'all',  label: '' /* will use t('filters.all') */ },
  { value: 'Base', label: 'Base' },
  { value: 'Tron', label: 'Tron' },
  { value: 'Sol',  label: 'Solana' },
]
const TOKEN_OPTIONS: ReadonlyArray<Token | 'all'> = ['all', 'USDC', 'USDT', 'ETH', 'DAI']

const PAGE_SIZE = 10

function truncate(value: string, head = 6, tail = 4): string {
  if (value.length <= head + tail + 1) return value
  return `${value.slice(0, head)}…${value.slice(-tail)}`
}

const selectStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 13,
  fontWeight: 500,
  color: COLORS.ink,
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 8,
  padding: '8px 28px 8px 12px',
  height: 36,
  cursor: 'pointer',
  outline: 'none',
  appearance: 'none',
  WebkitAppearance: 'none',
  backgroundImage:
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b6b6b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>\")",
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 10px center',
  backgroundSize: '12px',
}

const inputStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 13,
  fontWeight: 500,
  color: COLORS.ink,
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 8,
  padding: '8px 12px',
  height: 36,
  outline: 'none',
}

const exportBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 12,
  fontWeight: 600,
  color: COLORS.ink,
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 8,
  padding: '8px 14px',
  height: 36,
  cursor: 'pointer',
}

const pageBtnStyle = (disabled: boolean): React.CSSProperties => ({
  fontFamily: 'var(--font-display)',
  fontSize: 12,
  fontWeight: 600,
  color: disabled ? COLORS.subtle : COLORS.ink,
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 8,
  padding: '6px 14px',
  cursor: disabled ? 'not-allowed' : 'pointer',
})

export default function TransactionsPage() {
  const t = useTranslations('app.transactions')

  const [statusFilter, setStatusFilter] = useState<TxStatus | 'all'>('all')
  const [chainFilter, setChainFilter] = useState<Chain | 'all'>('all')
  const [tokenFilter, setTokenFilter] = useState<Token | 'all'>('all')
  const [dateFilter, setDateFilter] = useState<string>('')
  const [searchFilter, setSearchFilter] = useState<string>('')

  const { address } = useAccount()
  const { getAuthHeaders } = useWalletAuth(address)
  const [txs, setTxs] = useState<Tx[]>([])
  const [total, setTotal] = useState<number>(0)
  const [page, setPage] = useState<number>(1)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<boolean>(false)

  // Reset to page 1 whenever filters change (NOT when page itself changes).
  useEffect(() => {
    setPage(1)
  }, [statusFilter, chainFilter, tokenFilter, dateFilter, searchFilter])

  useEffect(() => {
    let cancelled = false
    if (!address) {
      setLoading(false)
      setTxs([])
      setTotal(0)
      setError(false)
      return
    }
    async function load(): Promise<void> {
      try {
        setLoading(true)
        const headers = await getAuthHeaders()
        const params = new URLSearchParams()
        params.set('page', String(page))
        params.set('per_page', String(PAGE_SIZE))
        if (statusFilter !== 'all') params.set('status', statusFilter)
        if (chainFilter !== 'all') params.set('chain', chainFilter)
        if (tokenFilter !== 'all') params.set('token', tokenFilter)
        if (dateFilter) params.set('date', dateFilter)
        if (searchFilter.trim()) params.set('search', searchFilter.trim())
        const res = await fetch(`/api/backend/api/v1/forwarding/logs?${params.toString()}`, { headers, cache: 'no-store' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = (await res.json()) as SweepLogsResponse
        if (cancelled) return
        const mapped: Tx[] = data.logs.map((row, idx) => {
          const ts = row.created_at ?? ''
          const dateOnly = ts.slice(0, 10)
          const dateObj = ts ? new Date(ts) : null
          const dateLabel = dateObj && !Number.isNaN(dateObj.getTime())
            ? dateObj.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
            : ''
          const tokenSym = (row.token_symbol ?? 'ETH').toUpperCase()
          const token: Token = ALLOWED_TOKENS.includes(tokenSym as Token) ? (tokenSym as Token) : 'ETH'
          return {
            id: row.id ?? idx + 1,
            date: dateOnly,
            dateLabel,
            hash: row.tx_hash ?? '',
            type: row.is_split ? 'Swap' : 'Send',
            to: (row.destination_wallet ?? '').toLowerCase(),
            amount: USD_FMT.format(row.amount_usd ?? 0),
            token,
            chain: 'Base',
            status: BE_TO_FE_STATUS[row.status] ?? 'pending',
          }
        })
        setTxs(mapped)
        setTotal(data.pagination?.total ?? 0)
        setError(false)
      } catch {
        if (!cancelled) {
          setError(true)
          setTxs([])
          setTotal(0)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [address, getAuthHeaders, page, statusFilter, chainFilter, tokenFilter, dateFilter, searchFilter])

  const visible = txs
  const from = total === 0 || visible.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = (page - 1) * PAGE_SIZE + visible.length

  return (
    <main className="rp-app-page">
      <style>{`@keyframes rsendsPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>
      {/* Export buttons */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 8,
          marginBottom: 16,
        }}
      >
        <button type="button" style={exportBtnStyle}>
          {t('exportCsv')}
        </button>
        <button type="button" style={exportBtnStyle}>
          {t('exportPdf')}
        </button>
      </div>

      {/* Filter row */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 16,
        }}
      >
        <select
          aria-label={t('filters.status')}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as TxStatus | 'all')}
          style={selectStyle}
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt === 'all' ? `${t('filters.all')} — ${t('filters.status')}` : t(`status.${opt}`)}
            </option>
          ))}
        </select>

        <select
          aria-label={t('filters.chain')}
          value={chainFilter}
          onChange={(e) => setChainFilter(e.target.value as Chain | 'all')}
          style={selectStyle}
        >
          {CHAIN_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.value === 'all' ? `${t('filters.all')} — ${t('filters.chain')}` : opt.label}
            </option>
          ))}
        </select>

        <select
          aria-label={t('filters.token')}
          value={tokenFilter}
          onChange={(e) => setTokenFilter(e.target.value as Token | 'all')}
          style={selectStyle}
        >
          {TOKEN_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt === 'all' ? `${t('filters.all')} — ${t('filters.token')}` : opt}
            </option>
          ))}
        </select>

        <input
          type="date"
          aria-label={t('filters.date')}
          value={dateFilter}
          onChange={(e) => setDateFilter(e.target.value)}
          style={{ ...inputStyle, minWidth: 150 }}
        />

        <input
          type="search"
          aria-label={t('filters.searchPlaceholder')}
          placeholder={t('filters.searchPlaceholder')}
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
          style={{ ...inputStyle, flex: '1 1 240px', minWidth: 240 }}
        />
      </div>

      {/* Table card */}
      <section
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: '4px 0 0',
          overflow: 'hidden',
        }}
      >
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: 'var(--font-display)',
              fontSize: 13,
            }}
          >
            <thead>
              <tr>
                {(['date', 'hash', 'type', 'to', 'amount', 'chain', 'status'] as const).map(
                  (col) => (
                    <th
                      key={col}
                      style={{
                        textAlign: 'left',
                        padding: '12px 14px',
                        borderBottom: `1px solid ${COLORS.border}`,
                        fontSize: 11,
                        fontWeight: 700,
                        color: COLORS.muted,
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        background: COLORS.paper,
                      }}
                    >
                      {t(`columns.${col}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {loading && visible.length === 0 ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={`skel-${i}`}>
                    <td colSpan={7} style={{ padding: '12px 14px', borderBottom: `1px solid ${COLORS.border}` }}>
                      <div style={{ height: 20, borderRadius: 6, background: '#e5e4e0', animation: 'rsendsPulse 1.5s ease-in-out infinite' }} />
                    </td>
                  </tr>
                ))
              ) : visible.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    style={{
                      padding: '40px 14px',
                      textAlign: 'center',
                      color: COLORS.subtle,
                      fontSize: 13,
                    }}
                  >
                    {t('empty')}
                  </td>
                </tr>
              ) : (
                visible.map((tx) => {
                  const chainBadge = CHAIN_BADGE[tx.chain]
                  const statusBadge = STATUS_BADGE[tx.status]
                  return (
                    <tr key={tx.id}>
                      <td
                        style={{
                          padding: '12px 14px',
                          color: COLORS.muted,
                          borderBottom: `1px solid ${COLORS.border}`,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tx.dateLabel}
                      </td>
                      <td
                        style={{
                          padding: '12px 14px',
                          color: COLORS.ink,
                          borderBottom: `1px solid ${COLORS.border}`,
                          fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
                          fontSize: 12,
                        }}
                      >
                        {truncate(tx.hash)}
                      </td>
                      <td
                        style={{
                          padding: '12px 14px',
                          color: COLORS.ink,
                          fontWeight: 600,
                          borderBottom: `1px solid ${COLORS.border}`,
                        }}
                      >
                        {tx.type}
                      </td>
                      <td
                        style={{
                          padding: '12px 14px',
                          color: COLORS.muted,
                          borderBottom: `1px solid ${COLORS.border}`,
                          fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
                          fontSize: 12,
                        }}
                      >
                        {truncate(tx.to)}
                      </td>
                      <td
                        style={{
                          padding: '12px 14px',
                          color: COLORS.ink,
                          fontWeight: 600,
                          borderBottom: `1px solid ${COLORS.border}`,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tx.amount}{' '}
                        <span style={{ color: COLORS.muted, fontWeight: 500, fontSize: 11 }}>
                          {tx.token}
                        </span>
                      </td>
                      <td style={{ padding: '12px 14px', borderBottom: `1px solid ${COLORS.border}` }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '3px 8px',
                            borderRadius: 6,
                            background: chainBadge.bg,
                            color: chainBadge.text,
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {tx.chain === 'Sol' ? 'Solana' : tx.chain}
                        </span>
                      </td>
                      <td style={{ padding: '12px 14px', borderBottom: `1px solid ${COLORS.border}` }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '3px 8px',
                            borderRadius: 6,
                            background: statusBadge.bg,
                            color: statusBadge.text,
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {t(`status.${tx.status}`)}
                        </span>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <footer
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '12px 16px',
            borderTop: `1px solid ${COLORS.border}`,
            background: COLORS.paper,
          }}
        >
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.muted }}>
            {t('pagination.showing', { from, to, total: total.toLocaleString() })}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              style={pageBtnStyle(page === 1 || loading)}
              disabled={page === 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              {t('pagination.prev')}
            </button>
            <button
              type="button"
              style={pageBtnStyle(page * PAGE_SIZE >= total || loading)}
              disabled={page * PAGE_SIZE >= total || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              {t('pagination.next')}
            </button>
          </div>
        </footer>
      </section>
    </main>
  )
}
