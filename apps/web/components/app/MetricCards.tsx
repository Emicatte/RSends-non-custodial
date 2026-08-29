'use client'

import { useTranslations } from 'next-intl'
import { card } from '@/components/app/pageStyles'

/**
 * The four KPI cards, lifted verbatim out of app/[locale]/app/page.tsx.
 *
 * Presentational: it takes already-formatted values and renders them. The
 * formatting stays on the page, because the page is what knows whether a value
 * came from a real stats read or from the `--` error row.
 *
 * Same reason as PaymentsTable — the marketing landing page renders these cards
 * against a fixture, so the merchant's dashboard and the shop window cannot
 * drift apart. Anything added here becomes public.
 */

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  green: '#2D8659',
  red: '#C03A3A',
}

export type Metric = {
  key: 'volume24h' | 'transactions24h' | 'totalBalance' | 'activeClients'
  value: string
  delta: string
  deltaPositive: boolean
  deltaIsCount?: boolean
}

export interface MetricCardsProps {
  metrics: ReadonlyArray<Metric>
  /** Show the value skeleton instead of the value. The page passes
   *  `loading && !stats` — a refresh over existing numbers must not blank them. */
  loading?: boolean
}

export function MetricCards({ metrics, loading = false }: MetricCardsProps) {
  const t = useTranslations('app.dashboard')

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {metrics.map((m) => {
        const deltaText = m.delta
        return (
          <div key={m.key} className={`${card} flex flex-col gap-1.5`}>
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
            {loading ? (
              <div className="h-8 w-3/5 rounded-lg" style={{ background: '#e5e4e0', animation: 'rsendsPulse 1.5s ease-in-out infinite' }} />
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
  )
}
