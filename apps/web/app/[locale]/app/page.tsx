'use client'

import type { CSSProperties } from 'react'
import { useTranslations } from 'next-intl'
import { GetStartedChecklist } from '@/components/app/GetStartedChecklist'
// The KPI cards moved to components/app so the marketing landing page can render
// the SAME cards the merchant sees. Values are unchanged; only the file.
import { MetricCards, type Metric } from '@/components/app/MetricCards'
import { VolumeTrendChart } from '@/components/app/VolumeTrendChart'
import { appPage, card } from '@/components/app/pageStyles'
import { useClientNow } from '@/hooks/useClientNow'
import { useOrgStats } from '@/hooks/useOrgStats'
import { useOrgVolumeSeries } from '@/hooks/useOrgVolumeSeries'

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

// Shared by the two exclusion notices. Quiet, not an error: excluded payments
// are a normal state, they just must never be silent.
const noticeStyle: CSSProperties = {
  margin: '-16px 0 0',
  fontSize: 12,
  lineHeight: 1.5,
  color: COLORS.muted,
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

// Deterministic fallback for the render passes that have no clock (see
// useClientNow). Locale and zone are pinned rather than resolved from the
// ambient environment, so the server and the browser always agree.
const ABS_TIME_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'UTC',
  timeZoneName: 'short',
})

/**
 * Relative label once the clock is available, absolute UTC before that.
 * `nowMs === null` on the server and the first client render, so both emit the
 * same absolute string; the relative form is a post-mount upgrade, never a
 * blank.
 */
function relTime(iso: string, nowMs: number | null): string {
  const ts = new Date(iso).getTime()
  if (!Number.isFinite(ts)) return ''
  if (nowMs === null) return ABS_TIME_FMT.format(ts)
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
  // Separate, unpolled read — see useOrgVolumeSeries. An error renders the
  // designed empty state rather than a chart built from nothing.
  const {
    buckets: series,
    unpricedCount: seriesUnpriced,
    loading: seriesLoading,
    error: seriesError,
  } = useOrgVolumeSeries(7)

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

  // Never `Date.now()` in the render body — see useClientNow.
  const nowMs = useClientNow()
  const txs: ReadonlyArray<TxRow> = (stats?.recent_transactions ?? []).map((r, idx) => ({
    id: r.id || idx + 1,
    time: relTime(r.timestamp_iso, nowMs),
    type: r.type,
    // `amount_usd` is meaningless when the token has no USD peg — the backend
    // sends 0.0 there and flags it. Rendering "$0" would claim a real payment
    // was worth nothing, so name the token instead.
    amount: r.amount_usd_known
      ? USD_FMT.format(r.amount_usd)
      : t('recentTransactions.amountUnpriced', { symbol: r.currency }),
    chain: FE_CHAINS.includes(r.chain) ? r.chain : 'Base',
    status: FE_STATUS_MAP[r.status] ?? 'pending',
  }))

  return (
    <main className={`${appPage} space-y-8`}>
      {/* Get started checklist — derived from the stats booleans; renders a
          layout-reserving skeleton while loading, nothing when all done (the
          parent's space-y owns the rhythm, so a null render leaves no gap) */}
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
      <MetricCards metrics={metrics} loading={loading && !stats} />

      {/* Payments the volume tile could not value. Without this line a
          merchant paid only in ETH reads "$0" and cannot tell it apart from
          having been paid nothing at all. Rendered only when there is
          something to disclose — a zero count says nothing and shows nothing. */}
      {!showErr && stats.volume_24h_unpriced_count > 0 && (
        <p data-testid="volume-unpriced-notice" style={noticeStyle}>
          {stats.volume_24h_unpriced_symbols.length > 0
            ? t('unpriced.volumeTokens', {
                count: stats.volume_24h_unpriced_count,
                symbols: stats.volume_24h_unpriced_symbols.join(', '),
              })
            : t('unpriced.volume', { count: stats.volume_24h_unpriced_count })}
        </p>
      )}

      {/* Volume trend chart */}
      <section className={card}>
        <h2
          className="m-0 mb-4"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            fontWeight: 700,
            color: COLORS.ink,
            letterSpacing: '-0.01em',
          }}
        >
          {t('volumeTrend.title')}
        </h2>
        {/* The chart's own window (7d), which is not the tile's (24h) — so it
            states its own exclusion rather than borrowing the one above. */}
        {!seriesError && seriesUnpriced > 0 && (
          <p
            data-testid="series-unpriced-notice"
            style={{ ...noticeStyle, marginTop: 0, marginBottom: 12 }}
          >
            {t('unpriced.series', { count: seriesUnpriced })}
          </p>
        )}
        <VolumeTrendChart
          buckets={seriesError ? null : series}
          loading={seriesLoading && !series}
        />
      </section>

      {/* Recent transactions */}
      <section className={card}>
        <header className="mb-4 flex items-center justify-between gap-3">
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
                    className="px-4 py-3"
                    style={{
                      textAlign: 'left',
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
                    <td className="px-4 py-3" style={{ color: COLORS.muted, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.time}
                    </td>
                    <td className="px-4 py-3" style={{ color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.type}
                    </td>
                    <td className="px-4 py-3" style={{ color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                      {tx.amount}
                    </td>
                    <td className="px-4 py-3" style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                      <span
                        className="inline-block px-2 py-0.5 rounded-md"
                        style={{
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
                    <td className="px-4 py-3" style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                      <span
                        className="inline-block px-2 py-0.5 rounded-md"
                        style={{
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
