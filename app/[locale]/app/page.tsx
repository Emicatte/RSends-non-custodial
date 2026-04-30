'use client'

import { Link } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  accent: '#C45A3C',
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
  Sol: { bg: 'rgba(153, 69, 255, 0.08)', text: '#7c2dc7' },
}

type TxStatus = 'confirmed' | 'pending' | 'failed'

const STATUS_BADGE: Record<TxStatus, { bg: string; text: string; key: 'statusConfirmed' | 'statusPending' | 'statusFailed' }> = {
  confirmed: { bg: COLORS.greenLight, text: COLORS.green, key: 'statusConfirmed' },
  pending: { bg: COLORS.orangeLight, text: COLORS.orange, key: 'statusPending' },
  failed: { bg: COLORS.redLight, text: COLORS.red, key: 'statusFailed' },
}

type Metric = {
  key: 'volume24h' | 'transactions24h' | 'totalBalance' | 'activeClients'
  value: string
  delta: string
  deltaPositive: boolean
  deltaIsCount?: boolean
}

const METRICS: ReadonlyArray<Metric> = [
  { key: 'volume24h',        value: '$48,291',  delta: '+12.3%',           deltaPositive: true },
  { key: 'transactions24h',  value: '127',      delta: '+8',               deltaPositive: true },
  { key: 'totalBalance',     value: '$182,450', delta: '',                 deltaPositive: true, deltaIsCount: true },
  { key: 'activeClients',    value: '14',       delta: '',                 deltaPositive: true, deltaIsCount: true },
]

type TxRow = {
  id: number
  time: string
  type: string
  amount: string
  chain: keyof typeof CHAIN_BADGE
  status: TxStatus
}

const TXS: ReadonlyArray<TxRow> = [
  { id: 1, time: '2 min ago',  type: 'Send', amount: '$1,250', chain: 'Base', status: 'confirmed' },
  { id: 2, time: '14 min ago', type: 'Swap', amount: '$3,400', chain: 'Tron', status: 'confirmed' },
  { id: 3, time: '32 min ago', type: 'Send', amount: '$890',   chain: 'Sol',  status: 'pending' },
  { id: 4, time: '1 hr ago',   type: 'Send', amount: '$5,200', chain: 'Base', status: 'confirmed' },
  { id: 5, time: '2 hr ago',   type: 'Swap', amount: '$420',   chain: 'Tron', status: 'failed' },
]

export default function AppDashboardPage() {
  const t = useTranslations('app.dashboard')

  return (
    <main style={{ padding: '24px 32px 80px', maxWidth: 1200, margin: '0 auto' }}>
      {/* Metric cards */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        style={{ marginBottom: 24 }}
      >
        {METRICS.map((m) => {
          let deltaText = m.delta
          if (m.deltaIsCount && m.key === 'totalBalance') {
            deltaText = t('metrics.chainsLabel', { count: 3 })
          } else if (m.deltaIsCount && m.key === 'activeClients') {
            deltaText = t('metrics.thisWeek', { count: 2 })
          }
          return (
            <div
              key={m.key}
              style={{
                background: COLORS.paper,
                border: `1px solid ${COLORS.border}`,
                borderRadius: 12,
                padding: '16px 18px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 11,
                  fontWeight: 700,
                  color: COLORS.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                }}
              >
                {t(`metrics.${m.key}`)}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 26,
                  fontWeight: 700,
                  color: COLORS.ink,
                  letterSpacing: '-0.02em',
                  lineHeight: 1.1,
                }}
              >
                {m.value}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 12,
                  fontWeight: 600,
                  color: m.deltaPositive ? COLORS.green : COLORS.red,
                }}
              >
                {deltaText}
              </div>
            </div>
          )
        })}
      </div>

      {/* Volume trend chart */}
      <section
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: '20px 22px',
          marginBottom: 24,
        }}
      >
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            fontWeight: 700,
            color: COLORS.ink,
            margin: '0 0 16px',
            letterSpacing: '-0.01em',
          }}
        >
          {t('volumeTrend.title')}
        </h2>
        <div
          style={{
            border: `1px dashed ${COLORS.border}`,
            borderRadius: 8,
            height: 240,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: COLORS.subtle,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {t('volumeTrend.comingSoon')}
        </div>
      </section>

      {/* Recent transactions */}
      <section
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: '20px 22px',
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 16,
            gap: 12,
          }}
        >
          <h2
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 14,
              fontWeight: 700,
              color: COLORS.ink,
              margin: 0,
              letterSpacing: '-0.01em',
            }}
          >
            {t('recentTransactions.title')}
          </h2>
          <Link
            href="/app/transactions"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              fontWeight: 600,
              color: COLORS.accent,
              textDecoration: 'none',
            }}
          >
            {t('recentTransactions.viewAll')} →
          </Link>
        </header>
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
                {(['time', 'type', 'amount', 'chain', 'status'] as const).map((col) => (
                  <th
                    key={col}
                    style={{
                      textAlign: 'left',
                      padding: '8px 12px',
                      borderBottom: `1px solid ${COLORS.border}`,
                      fontSize: 11,
                      fontWeight: 700,
                      color: COLORS.muted,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                    }}
                  >
                    {t(`recentTransactions.${col}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {TXS.map((tx) => {
                const chainBadge = CHAIN_BADGE[tx.chain]
                const statusBadge = STATUS_BADGE[tx.status]
                return (
                  <tr key={tx.id}>
                    <td style={{ padding: '12px', color: COLORS.muted, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.time}
                    </td>
                    <td style={{ padding: '12px', color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.type}
                    </td>
                    <td style={{ padding: '12px', color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.amount}
                    </td>
                    <td style={{ padding: '12px', borderBottom: `1px solid ${COLORS.border}` }}>
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '3px 8px',
                          borderRadius: 6,
                          background: chainBadge.bg,
                          color: chainBadge.text,
                          fontSize: 11,
                          fontWeight: 700,
                          letterSpacing: '0.02em',
                        }}
                      >
                        {tx.chain}
                      </span>
                    </td>
                    <td style={{ padding: '12px', borderBottom: `1px solid ${COLORS.border}` }}>
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
                        {t(`recentTransactions.${statusBadge.key}`)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}
