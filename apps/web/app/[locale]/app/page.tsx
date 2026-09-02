'use client'

import type { CSSProperties } from 'react'
import { useTranslations } from 'next-intl'
import { GetStartedChecklist } from '@/components/app/GetStartedChecklist'
// The KPI cards moved to components/app so the marketing landing page can render
// the SAME cards the merchant sees. Values are unchanged; only the file.
import { MetricCards, type Metric } from '@/components/app/MetricCards'
// The recent-settlements table moved to components/app for the same reason as
// the cards: the landing page's device mockup renders it against a fixture, so
// the marketing screenshot cannot drift from the dashboard. Formatting stays
// HERE — the page is what knows an amount has no USD peg.
import {
  RecentTransactionsTable,
  type TxRow,
  type TxStatus,
} from '@/components/app/RecentTransactionsTable'
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



const USD_FMT = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const FE_STATUS_MAP: Record<string, TxStatus> = {
  confirmed: 'confirmed',
  pending: 'pending',
  failed: 'failed',
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
  const pct30 = stats?.volume_30d_delta_pct ?? 0
  // Attempted is the denominator. 0 delivered of 0 attempted is "no webhooks
  // configured" and 0 of 12 is "every one failed" — rendering both as 0% would
  // merge two facts a merchant needs to tell apart, so the no-denominator case
  // gets an em-dash instead of an invented percentage.
  const hookSent = stats?.webhooks_delivered_24h ?? 0
  const hookTried = stats?.webhooks_attempted_24h ?? 0
  const metrics: ReadonlyArray<Metric> = showErr
    ? [
        { key: 'volume24h', value: '--', delta: '', deltaPositive: true },
        { key: 'transactions24h', value: '--', delta: '', deltaPositive: true },
        { key: 'volume30d', value: '--', delta: '', deltaPositive: true },
        { key: 'webhooksDelivered24h', value: '--', delta: '', deltaPositive: true, deltaIsCount: true },
      ]
    : [
        { key: 'volume24h', value: USD_FMT.format(stats.volume_24h), delta: `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`, deltaPositive: pct >= 0 },
        { key: 'transactions24h', value: String(stats.transactions_24h), delta: { key: 'metrics.vsYesterday', values: { count: `${txDelta >= 0 ? '+' : ''}${txDelta}` } }, deltaPositive: txDelta >= 0 },
        { key: 'volume30d', value: USD_FMT.format(stats.volume_30d), delta: `${pct30 >= 0 ? '+' : ''}${pct30.toFixed(1)}%`, deltaPositive: pct30 >= 0 },
        {
          key: 'webhooksDelivered24h',
          value: String(hookSent),
          delta: hookTried > 0
            ? { key: 'metrics.deliveryRate', values: { rate: Math.round((hookSent / hookTried) * 100) } }
            : '—',
          deltaPositive: hookSent === hookTried,
          deltaIsCount: true,
        },
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
    // Passed through, not filtered. The whitelist that used to sit here
    // rewrote every chain it did not recognise to the literal 'Base' — which
    // was six of the seven values the backend can send, including every Base
    // Sepolia settlement on a dashboard that only ever shows testnet.
    //
    // `?? ''` covers deploy skew, not a missing contract: web (Vercel) and the
    // backend (Render) ship independently, so a browser can hold a build that
    // reads `chain_key` while the API it is talking to does not yet send one.
    // Empty resolves to the neutral badge and no label — the dashboard says
    // nothing about the network rather than crashing or guessing 'Base'.
    chainKey: r.chain_key ?? '',
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
        <RecentTransactionsTable rows={txs} />
      </section>
    </main>
  )
}
