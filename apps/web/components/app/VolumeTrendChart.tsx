'use client'

/**
 * "Volume trend" card body for the /app home — settled USD volume per UTC day.
 *
 * Hand-drawn SVG rather than a charting library. For seven bars a library buys
 * nothing and costs plenty: `recharts` would be a first call site (~100kb for
 * seven rects, and its ResponsiveContainer measures the DOM so it cannot render
 * on the server), and `lightweight-charts` is canvas + imperative, so it draws
 * nothing server-side at all. This draws real markup on the server.
 *
 * HYDRATION SAFETY IS STRUCTURAL. The component is a pure function of its props
 * — no clock, no browser API, no measurement — and BOTH formatters below pin
 * their locale and timezone explicitly. `Intl.DateTimeFormat(undefined, …)`
 * would resolve to the server's ICU default during SSR and the visitor's
 * browser settings on the client, i.e. two different strings for one bucket,
 * which is a text mismatch and (with no Suspense boundary above /app) a
 * full-root client re-render. Pinned to UTC because the buckets ARE UTC days;
 * labelling a UTC bucket in local time would be a lie at the day boundary.
 *
 * SVG FOR GEOMETRY, HTML FOR LABELS. A viewBox that scales to the container
 * would shrink the day labels to ~6px on a 375px phone. So the bars scale
 * (`preserveAspectRatio="none"`, geometry only) while the seven labels are an
 * HTML flex row underneath, at a fixed readable size, needing no measurement.
 *
 * The empty state is designed, not defaulted: baseline and day labels stay
 * exactly where they are and only the bars and value gridlines drop out, so the
 * card holds its shape the moment the first payment settles.
 */

import { useTranslations } from 'next-intl'

export interface VolumeBucket {
  /** Bare UTC calendar date, `YYYY-MM-DD`, straight from the API. */
  date: string
  volume_usd: number
}

export interface VolumeTrendChartProps {
  /** `null` = not loaded or errored — rendered as the empty state, never as a
   *  chart, because a wrong chart is worse than an honest blank. */
  buckets: VolumeBucket[] | null
  loading: boolean
}

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  accent: '#C45A3C',
  border: '#e5e4e0',
  skeleton: '#e5e4e0',
}

// Pinned, never ambient — see the module docstring.
const DAY_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})
const USD_FMT = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

// SVG user units. Only the geometry lives in here; labels are HTML below it.
const VB_W = 700
const VB_H = 160
const BAR_GAP = 10 // user units between bars

function dayLabel(isoDate: string): string {
  // A date-only ISO string parses as UTC midnight per spec, which is exactly
  // the bucket's instant — no local-time drift.
  const ts = Date.parse(isoDate)
  return Number.isFinite(ts) ? DAY_FMT.format(ts) : isoDate
}

export function VolumeTrendChart({ buckets, loading }: VolumeTrendChartProps) {
  const t = useTranslations('app.dashboard.volumeTrend')

  // One frame for every state: same height, same radius, so nothing shifts.
  const frame = 'h-60 w-full rounded-lg'

  if (loading) {
    return (
      <div
        className={`${frame} flex flex-col`}
        data-testid="volume-trend-frame"
        aria-hidden="true"
      >
        <div
          className="flex-1 rounded-lg"
          data-testid="volume-trend-skeleton"
          style={{
            background: COLORS.skeleton,
            animation: 'rsendsPulse 1.5s ease-in-out infinite',
          }}
        />
      </div>
    )
  }

  const days = buckets ?? []
  const peak = days.reduce((m, b) => Math.max(m, b.volume_usd || 0), 0)
  const isEmpty = days.length === 0 || peak <= 0

  return (
    <div className={`${frame} flex flex-col`} data-testid="volume-trend-frame">
      {/* Value axis: the peak, top-left, in mono. Omitted when there is no
          peak to state — an axis labelled "$0" is noise, not information. */}
      <div
        className="mb-1 flex items-baseline justify-between"
        style={{
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: 11,
          color: COLORS.subtle,
        }}
      >
        <span>{isEmpty ? '' : USD_FMT.format(peak)}</span>
        <span>{isEmpty ? '' : t('axisLabel')}</span>
      </div>

      {/* Plot area */}
      <div className="relative min-h-0 flex-1">
        {isEmpty && (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-4 text-center"
            data-testid="volume-trend-empty"
          >
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 13,
                fontWeight: 600,
                color: COLORS.muted,
              }}
            >
              {t('empty')}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 12,
                color: COLORS.subtle,
              }}
            >
              {t('emptyHint')}
            </span>
          </div>
        )}

        {!isEmpty && (
          <svg
            className="block h-full w-full"
            viewBox={`0 0 ${VB_W} ${VB_H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={t('axisLabel')}
          >
            {/* Value gridlines — only ever drawn when there is a value to
                grid. Quarter steps, purely decorative. */}
            {[0.25, 0.5, 0.75].map((f) => (
              <line
                key={f}
                data-testid="volume-gridline"
                x1={0}
                x2={VB_W}
                y1={VB_H * f}
                y2={VB_H * f}
                stroke={COLORS.border}
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {days.map((b, i) => {
              const slot = VB_W / days.length
              const w = Math.max(slot - BAR_GAP, 1)
              const x = i * slot + BAR_GAP / 2
              // Floor at 2 user units so a settled-but-tiny day is still
              // visible rather than silently rounding to nothing.
              const h = Math.max((b.volume_usd / peak) * VB_H, b.volume_usd > 0 ? 2 : 0)
              return (
                <rect
                  key={b.date}
                  data-testid="volume-bar"
                  x={x}
                  y={VB_H - h}
                  width={w}
                  height={h}
                  rx={2}
                  fill={COLORS.accent}
                />
              )
            })}
          </svg>
        )}

        {/* Baseline — present in BOTH states. It is what makes the empty card
            read as a chart at rest instead of a hole. */}
        <div
          data-testid="volume-baseline"
          className="absolute inset-x-0 bottom-0"
          style={{ borderBottom: `1px solid ${COLORS.border}` }}
        />
      </div>

      {/* Day labels as HTML, so they stay legible at any container width.
          `clamp` rather than a measured breakpoint: seven "Aug 14" labels at a
          flat 11px wrap to two lines below ~360px (measured), which makes the
          row jump in height. Pure CSS keeps the markup identical on the server
          and the client. `nowrap` is the hard guarantee. */}
      <div
        className="mt-2 flex w-full justify-between"
        style={{
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: 'clamp(9px, 2.6vw, 11px)',
          color: COLORS.muted,
        }}
      >
        {(days.length ? days : []).map((b) => (
          <span
            key={b.date}
            data-testid="volume-day-label"
            className="flex-1 whitespace-nowrap text-center"
          >
            {dayLabel(b.date)}
          </span>
        ))}
      </div>
    </div>
  )
}
