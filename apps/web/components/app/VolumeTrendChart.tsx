'use client'

/**
 * "Volume trend" card body for the /app home — settled USD volume per UTC day.
 *
 * Hand-drawn rather than a charting library. For seven bars a library buys
 * nothing and costs plenty: `recharts` would be a first call site (~100kb for
 * seven rects, and its ResponsiveContainer measures the DOM so it cannot render
 * on the server), and `lightweight-charts` is canvas + imperative, so it draws
 * nothing server-side at all. This draws real markup on the server.
 *
 * HYDRATION SAFETY IS STRUCTURAL. The component is a pure function of its props
 * — no clock, no browser API, no measurement — and every formatter below pins
 * its locale (and, for dates, its timezone) explicitly. `Intl.DateTimeFormat(
 * undefined, …)` would resolve to the server's ICU default during SSR and the
 * visitor's browser settings on the client, i.e. two different strings for one
 * bucket, which is a text mismatch and (with no Suspense boundary above /app) a
 * full-root client re-render. Pinned to UTC because the buckets ARE UTC days;
 * labelling a UTC bucket in local time would be a lie at the day boundary. The
 * axis abbreviation is hand-rolled arithmetic rather than `notation: 'compact'`
 * for the same reason one layer down: pinning the locale does not pin the ICU
 * *version*, and Node's compact-decimal patterns need not match the browser's.
 *
 * PLAIN HTML, NOT SVG. The bars were `<rect>`s in a `preserveAspectRatio="none"`
 * viewBox, which stretches user units by container width — so a bar's rendered
 * width scaled with the viewport and capping it at N pixels was not practical
 * (`stroke-width` + `non-scaling-stroke` can hold a pixel width, but it rounds
 * both ends of the bar, cannot express `min(slot, cap)`, and is measured in the
 * canvas coordinate system, which the grow-in transform below disturbs). Divs
 * with percentage heights are just as declarative — no measurement, so still
 * SSR-identical — cap their width in real pixels, and are the hover and focus
 * targets themselves rather than needing a second overlay.
 *
 * THE READER CAN INTERROGATE IT. Every day — including a quiet one — carries its
 * date and exact amount as an accessible name and reveals a tooltip on hover or
 * focus. The seven days are ONE tab stop with arrow-key traversal (roving
 * tabindex), not seven: this card sits on a dashboard that already has a nav, a
 * sidebar, a checklist and a table, and a reader tabbing past it should not pay
 * seven stops for a supporting detail. The tooltip is absolutely positioned, so
 * it overlays and never reflows the card, and it is held inside the plot by a
 * CSS `clamp()` rather than by measuring anything — an index-based rule ("pin
 * the first and last") is really a WIDTH-based rule in disguise and breaks on a
 * narrow phone, where the second and second-to-last bars overflow too.
 *
 * The empty state is designed, not defaulted: baseline, axis column and day
 * labels stay exactly where they are and only the bars, ticks and gridlines drop
 * out, so the card holds its shape the moment the first payment settles.
 */

import { useRef, useState } from 'react'
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
  grid: '#f0efeb', // lighter than the baseline: the axis line must read stronger
  skeleton: '#e5e4e0',
}

/** The class carrying the grow-in, declared in `globals.css`. Exported so the
 *  test that proves the animation is disable-able under reduced motion can
 *  check the component and the stylesheet agree on the name. */
export const BAR_ANIMATION_CLASS = 'rsends-bar'

// Pinned, never ambient — see the module docstring.
const DAY_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})
/** Narrow-viewport day label — see the label row for why there are two. */
const DAY_NUM_FMT = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  timeZone: 'UTC',
})
/** Whole dollars, for axis ticks below $1,000. */
const USD_FMT = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})
/** Tooltip and text alternative: the interrogation surface, so cents included —
 *  the API already returns the value rounded to two places. Nothing a merchant
 *  reconciles against their own records is abbreviated. */
const USD_EXACT_FMT = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Bar width cap, CSS pixels. Seven bars stretched across a 1000px card read as
 *  the subject of the page; this card is a supporting detail. */
const MAX_BAR_W = 32
/** Gap between a bar and its slot edge, so bars never touch on a narrow phone
 *  where the cap is not what binds. */
const BAR_GAP = 6
/** Percent of the plot. Floors a settled-but-tiny day so it stays visible rather
 *  than sub-pixel-rounding away — the shorter the plot, the more this matters. */
const MIN_BAR_PCT = 2
/** Tooltip width, in rem so it tracks the root font size the same way the
 *  `clamp()` that positions it does. */
const TIP_W = 6
const TIP_HALF = TIP_W / 2

// Visually hidden, but immediately available to screen readers — the inline
// pattern used by GetStartedChecklist and TypewriterHeadline.
const SR_ONLY: React.CSSProperties = {
  position: 'absolute',
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
}

function dayLabel(isoDate: string): string {
  // A date-only ISO string parses as UTC midnight per spec, which is exactly
  // the bucket's instant — no local-time drift.
  const ts = Date.parse(isoDate)
  return Number.isFinite(ts) ? DAY_FMT.format(ts) : isoDate
}

function dayNumber(isoDate: string): string {
  const ts = Date.parse(isoDate)
  return Number.isFinite(ts) ? DAY_NUM_FMT.format(ts) : isoDate
}

/**
 * Axis tick text. Abbreviated above $1,000 so the axis column stays 32px wide at
 * any magnitude and never squeezes the seven day labels beside it. Plain
 * arithmetic and `toFixed`, both spec-exact, so the tick cannot disagree between
 * the server pass and the browser the way an ICU compact pattern could.
 */
export function tickLabel(value: number): string {
  if (value < 999.5) return USD_FMT.format(value) // "$0" … "$999"
  if (value < 999_500) return `$${abbreviate(value / 1000)}K`
  return `$${abbreviate(value / 1_000_000)}M`
}

/**
 * One decimal below ten, none above — so the tick is never wider than five
 * characters. The `9.95` threshold rather than `10` is what stops `$9,999`
 * rounding into a six-character `$10.0K`; the band boundaries in `tickLabel`
 * stop `$999,600` becoming `$1000K` for the same reason.
 */
function abbreviate(n: number): string {
  return n < 9.95 ? n.toFixed(1) : String(Math.round(n))
}

/**
 * Where the tooltip for bar `i` of `n` sits inside the plot. The ideal position
 * centres it on the bar; `clamp` holds it inside the plot's left and right edges
 * when that would hang it outside the card. Doing this in CSS rather than in JS
 * is what keeps the component measurement-free — and correct at every width,
 * unlike a rule that special-cases the first and last bar only.
 */
export function tooltipLeft(i: number, n: number): string {
  const centre = (((i + 0.5) * 100) / n).toFixed(4)
  return `clamp(0px, calc(${centre}% - ${TIP_HALF}rem), calc(100% - ${TIP_W}rem))`
}

export function VolumeTrendChart({ buckets, loading }: VolumeTrendChartProps) {
  const t = useTranslations('app.dashboard.volumeTrend')
  const [active, setActive] = useState<number | null>(null)
  // Roving tabindex. Seeded to 0 rather than derived from `active` (which is
  // `null` until the reader points at something) so the SERVER pass emits a
  // tabbable slot: deriving it would ship a chart nobody can tab into.
  const [focusIndex, setFocusIndex] = useState(0)
  const groupRef = useRef<HTMLDivElement | null>(null)
  const slotRefs = useRef<(HTMLDivElement | null)[]>([])

  // One frame for every state: same height, same radius, so nothing shifts.
  const frame = 'h-32 w-full rounded-lg'
  // The value-axis column, and the matching indent under it so the day labels
  // line up with the plot rather than with the ticks.
  const axisCol = 'w-8 shrink-0'
  const axisPad = 'pl-8'

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

  const tickStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono, monospace)',
    // Deliberately below the day labels at EVERY width (they are 8→11px).
    fontSize: 'clamp(7px, 1.9vw, 9px)',
    // `muted`, not `subtle`: these are informational, and #9a9a9a is 2.8:1 on
    // white. Subordinate is a matter of size here, not of being hard to read.
    color: COLORS.muted,
    // Load-bearing: `translateY(-50%)` only centres the tick on its gridline if
    // the line box is the glyph box.
    lineHeight: 1,
  }

  /** Move the roving focus, wrapping at both ends. */
  const moveFocus = (from: number, delta: number) => {
    const next = (from + delta + days.length) % days.length
    setFocusIndex(next)
    slotRefs.current[next]?.focus()
  }

  return (
    <div className={`${frame} flex flex-col`} data-testid="volume-trend-frame">
      <div className="flex min-h-0 flex-1">
        {/* Value axis: zero, midpoint and peak, each centred on its gridline.
            The ticks are omitted when there is no peak to state — an axis
            reading "$0 / $0 / $0" is noise — but the COLUMN is always rendered,
            so nothing shifts sideways when the first payment lands. */}
        <div className={`${axisCol} relative`} aria-hidden="true">
          {!isEmpty &&
            [
              { key: 'max', at: 0, value: peak },
              { key: 'mid', at: 0.5, value: peak / 2 },
              { key: 'zero', at: 1, value: 0 },
            ].map((tick) => (
              <span
                key={tick.key}
                data-testid="volume-axis-tick"
                className="absolute right-1"
                style={{
                  ...tickStyle,
                  top: `${tick.at * 100}%`,
                  transform: 'translateY(-50%)',
                }}
              >
                {tickLabel(tick.value)}
              </span>
            ))}
        </div>

        {/* Plot area */}
        <div className="relative min-h-0 min-w-0 flex-1">
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
            <>
              {/* Gridlines, aligned to the ticks. The third line of the axis is
                  the baseline further down, which is drawn stronger because it
                  is the axis rather than its grid. Both layers below are
                  absolutely positioned, so DOM order decides paint order and a
                  gridline can never cross in front of a bar — a STATIC bar row
                  would lose to them no matter what the source order said. */}
              {[
                { key: 'max', at: '0%' },
                { key: 'mid', at: '50%' },
              ].map((line) => (
                <div
                  key={line.key}
                  data-testid="volume-gridline"
                  className="pointer-events-none absolute inset-x-0"
                  style={{ top: line.at, borderTop: `1px solid ${COLORS.grid}` }}
                  aria-hidden="true"
                />
              ))}

              {/* One slot per day — the bar's container AND its hit target, so a
                  quiet day (which draws no bar) is hoverable and focusable all
                  the same. `mouseleave` is handled on the GROUP: per slot it
                  would fire on every slot-to-slot move and blank the tooltip for
                  a frame. */}
              <div
                ref={groupRef}
                role="group"
                aria-label={t('axisLabel')}
                className="absolute inset-0 flex"
                onMouseLeave={() => setActive(null)}
              >
                {days.map((b, i) => {
                  const value = b.volume_usd > 0 ? b.volume_usd : 0
                  const pct = Math.max((value / peak) * 100, MIN_BAR_PCT)
                  return (
                    <div
                      key={b.date}
                      ref={(el) => {
                        slotRefs.current[i] = el
                      }}
                      data-testid="volume-day-slot"
                      className="rsends-chart-slot relative min-w-0 flex-1"
                      role="img"
                      aria-label={`${dayLabel(b.date)}: ${USD_EXACT_FMT.format(value)}`}
                      tabIndex={i === focusIndex ? 0 : -1}
                      onMouseEnter={() => setActive(i)}
                      onFocus={() => {
                        setFocusIndex(i)
                        setActive(i)
                      }}
                      onBlur={(e) => {
                        // Arrow-keying to a sibling is not leaving the chart.
                        const next = e.relatedTarget as Node | null
                        if (next && groupRef.current?.contains(next)) return
                        setActive((cur) => (cur === i ? null : cur))
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          setActive(null)
                        } else if (e.key === 'ArrowRight') {
                          e.preventDefault()
                          moveFocus(i, 1)
                        } else if (e.key === 'ArrowLeft') {
                          e.preventDefault()
                          moveFocus(i, -1)
                        } else if (e.key === 'Home') {
                          e.preventDefault()
                          moveFocus(0, 0)
                        } else if (e.key === 'End') {
                          e.preventDefault()
                          moveFocus(days.length - 1, 0)
                        }
                      }}
                    >
                      {value > 0 && (
                        <div
                          data-testid="volume-bar"
                          className={`${BAR_ANIMATION_CLASS} absolute bottom-0 left-0`}
                          aria-hidden="true"
                          style={{
                            height: `${pct.toFixed(4)}%`,
                            width: `calc(100% - ${BAR_GAP}px)`,
                            maxWidth: MAX_BAR_W,
                            background: COLORS.accent,
                            borderRadius: '2px 2px 0 0',
                          }}
                        />
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Tooltip: overlays the plot, so it can neither reflow the card
                  nor spill past it vertically. `pointer-events-none` is not
                  cosmetic — an opaque box over the slots would eat its own
                  `mouseleave` and flicker. Hidden from assistive tech because
                  the focused slot's accessible name already says the same. */}
              {active !== null && days[active] && (
                <div
                  data-testid="volume-tooltip"
                  className="pointer-events-none absolute top-0 rounded border px-1.5 py-1 text-center"
                  aria-hidden="true"
                  style={{
                    left: tooltipLeft(active, days.length),
                    minWidth: `${TIP_W}rem`,
                    background: '#ffffff',
                    borderColor: COLORS.border,
                    boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: 10,
                    lineHeight: 1.3,
                    whiteSpace: 'nowrap',
                  }}
                >
                  <span style={{ color: COLORS.muted }}>
                    {dayLabel(days[active].date)}
                  </span>
                  <br />
                  <span style={{ color: COLORS.ink, fontWeight: 500 }}>
                    {USD_EXACT_FMT.format(
                      days[active].volume_usd > 0 ? days[active].volume_usd : 0,
                    )}
                  </span>
                </div>
              )}
            </>
          )}

          {/* Baseline — present in BOTH states, and the axis's zero line. It is
              what makes an empty card read as a chart at rest instead of a hole,
              and a quiet day read as measured instead of missing. */}
          <div
            data-testid="volume-baseline"
            className="pointer-events-none absolute inset-x-0 bottom-0"
            style={{ borderBottom: `1px solid ${COLORS.border}` }}
            aria-hidden="true"
          />
        </div>
      </div>

      {/* Day labels as HTML, so they stay legible at any container width.
          `clamp` rather than a measured breakpoint: seven labels at a flat size
          wrap below ~360px, which makes the row jump in height. `nowrap` is the
          hard guarantee, and `min-w-0` is the backstop behind it — `flex-1`
          defaults to `min-width: auto`, so without it an over-wide label would
          widen the row, the card and the page into horizontal scroll on a
          phone. `pl-8` matches the axis column, so each label sits under the bar
          it names.

          TWO LABELS, ONE VISIBLE. The axis column takes 32px off this row, which
          leaves a ~29px slot at 320px — and "Aug 20" is ~29px at the clamp's 9px
          floor, so the seven ran together into one unreadable string (measured
          in Chrome: 0.6px between them). Below `sm` the label is therefore the
          day of the month alone; the month returns as soon as there is room for
          it. Both are in the markup and CSS picks one, so the server and the
          client still emit identical HTML — a width-derived choice in JS would
          not. The full date is never lost: it is in the tooltip, in each slot's
          accessible name, and in the text alternative. */}
      <div
        className={`mt-2 flex w-full ${axisPad}`}
        style={{
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: 'clamp(9px, 2.6vw, 11px)',
          color: COLORS.muted,
        }}
        aria-hidden="true"
      >
        {days.map((b) => (
          <span
            key={b.date}
            data-testid="volume-day-label"
            className="min-w-0 flex-1 whitespace-nowrap text-left"
          >
            <span className="sm:hidden">{dayNumber(b.date)}</span>
            <span className="hidden sm:inline">{dayLabel(b.date)}</span>
          </span>
        ))}
      </div>

      {/* Text alternative: the series as readable values, for a reader who never
          points at anything. Every drawn layer above is aria-hidden, so the only
          things exposed are this list and the seven labelled slots. */}
      {!isEmpty && (
        <ul data-testid="volume-alt-text" style={SR_ONLY}>
          <li>{t('axisLabel')}</li>
          {days.map((b) => (
            <li key={b.date}>
              {dayLabel(b.date)}:{' '}
              {USD_EXACT_FMT.format(b.volume_usd > 0 ? b.volume_usd : 0)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
