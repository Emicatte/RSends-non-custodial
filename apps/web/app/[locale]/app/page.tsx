'use client'

import { useTranslations } from 'next-intl'
import { GetStartedChecklist } from '@/components/app/GetStartedChecklist'
import { useOrgStats } from '@/hooks/useOrgStats'

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

const USD_FMT = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const FE_CHAINS: ReadonlyArray<string> = ['Base', 'Tron', 'Sol']
const FE_STATUS_MAP: Record<string, TxStatus> = {
  confirmed: 'confirmed',
  pending: 'pending',
  failed: 'failed',
}

type TxRow = {
  id: number
  time: string
  type: string
  amount: string
  chain: keyof typeof CHAIN_BADGE
  status: TxStatus
}

const RTF = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

function relTime(iso: string, nowMs: number): string {
  const ts = new Date(iso).getTime()
  if (!Number.isFinite(ts)) return ''
  const diffSec = Math.round((ts - nowMs) / 1000)
  const abs = Math.abs(diffSec)
  if (abs < 60) return RTF.format(diffSec, 'second')
  if (abs < 3600) return RTF.format(Math.round(diffSec / 60), 'minute')
  if (abs < 86400) return RTF.format(Math.round(diffSec / 3600), 'hour')
  return RTF.format(Math.round(diffSec / 86400), 'day')
}

export default function AppDashboardPage() {
  const t = useTranslations('app.dashboard')

  // Phase E: the home widget now reads the session-authed, correctly-scoped
  // org stats (settlement_wallet join + USD conversion) instead of the
  // wallet-signature `dashboard/stats` whose primary-wallet scope broke post-B.
  const { stats, loading, error } = useOrgStats()

  const showErr = error || !stats
  const pct = stats?.volume_24h_delta_pct ?? 0
  const txDelta = stats?.transactions_24h_delta ?? 0
  const metrics: ReadonlyArray<Metric> = showErr
    ? [
        { key: 'volume24h', value: '--', delta: '', deltaPositive: true },
        { key: 'transactions24h', value: '--', delta: '', deltaPositive: true },
        { key: 'totalBalance', value: '--', delta: '', deltaPositive: true, deltaIsCount: true },
        { key: 'activeClients', value: '--', delta: '', deltaPositive: true, deltaIsCount: true },
      ]
    : [
        { key: 'volume24h', value: USD_FMT.format(stats.volume_24h), delta: `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`, deltaPositive: pct >= 0 },
        { key: 'transactions24h', value: String(stats.transactions_24h), delta: `${txDelta >= 0 ? '+' : ''}${txDelta}`, deltaPositive: txDelta >= 0 },
        { key: 'totalBalance', value: USD_FMT.format(stats.total_balance), delta: t('metrics.chainsLabel', { count: stats.total_balance_chains }), deltaPositive: true, deltaIsCount: true },
        { key: 'activeClients', value: String(stats.active_clients), delta: t('metrics.thisWeek', { count: stats.active_clients_this_week }), deltaPositive: true, deltaIsCount: true },
      ]

  const nowMs = Date.now()
  const txs: ReadonlyArray<TxRow> = (stats?.recent_transactions ?? []).map((r, idx) => ({
    id: r.id || idx + 1,
    time: relTime(r.timestamp_iso, nowMs),
    type: r.type,
    amount: USD_FMT.format(r.amount_usd),
    chain: FE_CHAINS.includes(r.chain) ? r.chain : 'Base',
    status: FE_STATUS_MAP[r.status] ?? 'pending',
  }))

  return (
    <main className="rp-app-page">
      <style>{`@keyframes rsendsPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>
      {/* Get started checklist — derived from the stats booleans; renders a
          layout-reserving skeleton while loading, nothing when all done (the
          component owns its bottom margin so a null render leaves no gap) */}
      <GetStartedChecklist
        loading={loading && !stats}
        completed={
          stats
            ? {
                wallet: stats.settlement_wallet_set,
                apiKey: stats.has_api_key,
                testPayment: stats.has_paid_payment,
              }
            : null
        }
      />
      {/* Metric cards */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        style={{ marginBottom: 24 }}
      >
        {metrics.map((m) => {
          const deltaText = m.delta
          return (
            <div
              key={m.key}
              className="rp-stat-card"
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
              {loading && !stats ? (
                <div style={{ height: 32, width: '60%', borderRadius: 8, background: '#e5e4e0', animation: 'rsendsPulse 1.5s ease-in-out infinite' }} />
              ) : (
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
              )}
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
          {/* "View all" link removed in Phase A (custodial /app/transactions gone);
              Phase C re-adds it pointing at the real /app/payments list. */}
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
              {txs.map((tx) => {
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
