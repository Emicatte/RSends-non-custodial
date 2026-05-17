'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'

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

const TXS: ReadonlyArray<Tx> = [
  { id: 1,  date: '2026-04-30', dateLabel: '30 Apr 2026, 14:32', hash: '0x4f3e9c2a8b1d7e5f4a3b2c1d0e9f8a7b6c5d4e3a2bc8f1d', type: 'Send', to: '0x7a1b9c8d4e2f3a5b6c7d8e9f0a1b2c3d4e5f9d2', amount: '$1,250', token: 'USDC', chain: 'Base', status: 'confirmed' },
  { id: 2,  date: '2026-04-30', dateLabel: '30 Apr 2026, 13:18', hash: '0x8c2a7e3f9d1b5e4a6c8f0d2b4a6e8c1d3f5a91ef', type: 'Swap', to: '0xb4d18e6c2a4f9e7d1b3c5a7e9f0b2d4c6a83a87', amount: '$3,400', token: 'USDT', chain: 'Tron', status: 'confirmed' },
  { id: 3,  date: '2026-04-30', dateLabel: '30 Apr 2026, 12:45', hash: '0x1d9f4c5b3e7a8d2f6b0a9c1e4d7f8b2a5c4c5b', type: 'Send', to: '0x2e88c1a37b4d9e2f5a6b8c0d1e3f4a5b7d9c1a3', amount: '$890',   token: 'USDC', chain: 'Sol',  status: 'pending'   },
  { id: 4,  date: '2026-04-30', dateLabel: '30 Apr 2026, 11:30', hash: '0x6b278e4d1a3f7c5b9d0e2a4c6f8b1e3d5a78e4d', type: 'Send', to: '0x9c14f0b62a8d4e7c1b3a5d9e0f2b4c6a8d3f0b6', amount: '$5,200', token: 'DAI',  chain: 'Base', status: 'confirmed' },
  { id: 5,  date: '2026-04-30', dateLabel: '30 Apr 2026, 10:15', hash: '0x3a8ed2f74b1c6a9e0d8b2f5c7a3e6b1d4f8d2f7', type: 'Swap', to: '0x55a3e8b91c7d4f2a6b0e8c1d3f5a7b9d2c4e8b9', amount: '$420',   token: 'ETH',  chain: 'Tron', status: 'failed'    },
  { id: 6,  date: '2026-04-29', dateLabel: '29 Apr 2026, 22:50', hash: '0x9e1c7b34a8f2d5e6b0c4a9d1e3f8b2c5a7d7b34', type: 'Send', to: '0xd2f50916e8b3c7a1d4f6b9c2e5a8d0b3c6e0916', amount: '$2,100', token: 'USDC', chain: 'Base', status: 'confirmed' },
  { id: 7,  date: '2026-04-29', dateLabel: '29 Apr 2026, 19:22', hash: '0x2f6b51ac9d3e7a4f8b1c5d6e9a0b2c4f7d51ac', type: 'Send', to: '0x081e4d22b6a9c3f5e8d1b4c7a0f2e5b8d2c4d22', amount: '$760',   token: 'USDT', chain: 'Sol',  status: 'confirmed' },
  { id: 8,  date: '2026-04-29', dateLabel: '29 Apr 2026, 16:08', hash: '0xc70d3f9a2e8b1d4c6f5a9b0e7d2c4a8f5e3f9a', type: 'Swap', to: '0x4b7cf8a16e3d9b2c5a0f8e7d4b1a6c9e3df8a1', amount: '$1,800', token: 'USDC', chain: 'Base', status: 'pending'   },
  { id: 9,  date: '2026-04-29', dateLabel: '29 Apr 2026, 14:45', hash: '0x5421e0bd8c3a9f2d6b4e7a1c5f0d8e2b9a3e0bd', type: 'Send', to: '0x6cd82a14e5b8d1f3a7c0e9b4d2c5f8a1e6b2a14', amount: '$3,950', token: 'DAI',  chain: 'Tron', status: 'confirmed' },
  { id: 10, date: '2026-04-29', dateLabel: '29 Apr 2026, 11:30', hash: '0xb8a419c5d7e3f2a6b0c8e1d4f9a2b5c7e3119c5', type: 'Send', to: '0xf34107ee2c6b8a4d1f9e3b7c0a5d2f8e6b407ee', amount: '$620',   token: 'ETH',  chain: 'Base', status: 'failed'    },
  { id: 11, date: '2026-04-28', dateLabel: '28 Apr 2026, 23:15', hash: '0x7f1244d8b2e6a9c3f0d8e1b5a4c7f2d6e944d8',  type: 'Swap', to: '0xae23c5b04f7e9d2a6b8c1f0d3e5a8b2c4d6c5b0', amount: '$4,750', token: 'USDC', chain: 'Sol',  status: 'confirmed' },
  { id: 12, date: '2026-04-28', dateLabel: '28 Apr 2026, 18:30', hash: '0x0c5e82ab9f3d4a7c1b8e6d0f2a5b9c4e7d182ab', type: 'Send', to: '0x33b07d4ea5c1f8b9d2e6a4c0f7b3d8e1a5c87d4e', amount: '$1,150', token: 'USDT', chain: 'Base', status: 'confirmed' },
]

const STATUS_OPTIONS: ReadonlyArray<TxStatus | 'all'> = ['all', 'confirmed', 'pending', 'failed']
const CHAIN_OPTIONS: ReadonlyArray<{ value: Chain | 'all'; label: string }> = [
  { value: 'all',  label: '' /* will use t('filters.all') */ },
  { value: 'Base', label: 'Base' },
  { value: 'Tron', label: 'Tron' },
  { value: 'Sol',  label: 'Solana' },
]
const TOKEN_OPTIONS: ReadonlyArray<Token | 'all'> = ['all', 'USDC', 'USDT', 'ETH', 'DAI']

const FAKE_TOTAL = 1247
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

  const filtered = useMemo(() => {
    const q = searchFilter.trim().toLowerCase()
    return TXS.filter((tx) => {
      if (statusFilter !== 'all' && tx.status !== statusFilter) return false
      if (chainFilter !== 'all' && tx.chain !== chainFilter) return false
      if (tokenFilter !== 'all' && tx.token !== tokenFilter) return false
      if (dateFilter && tx.date !== dateFilter) return false
      if (q && !tx.hash.toLowerCase().includes(q) && !tx.to.toLowerCase().includes(q)) return false
      return true
    })
  }, [statusFilter, chainFilter, tokenFilter, dateFilter, searchFilter])

  const anyFilterActive =
    statusFilter !== 'all' ||
    chainFilter !== 'all' ||
    tokenFilter !== 'all' ||
    dateFilter !== '' ||
    searchFilter.trim() !== ''

  const visible = filtered.slice(0, PAGE_SIZE)
  const total = anyFilterActive ? filtered.length : FAKE_TOTAL
  const from = visible.length === 0 ? 0 : 1
  const to = visible.length

  return (
    <main className="rp-app-page">
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
              {visible.length === 0 ? (
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
            <button type="button" style={pageBtnStyle(true)} disabled>
              {t('pagination.prev')}
            </button>
            <button type="button" style={pageBtnStyle(true)} disabled>
              {t('pagination.next')}
            </button>
          </div>
        </footer>
      </section>
    </main>
  )
}
