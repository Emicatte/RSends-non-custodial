/**
 * The /app "Volume trend (7d)" card.
 *
 * Properties, in the order they matter:
 *
 *  1. With data, every day gets a SLOT — seven days in, seven slots out — and
 *     every day with volume gets a bar inside its slot. A quiet day keeps its
 *     slot, its label and the baseline and draws no bar: "nothing settled that
 *     day", not "data missing".
 *  2. With no data at all, the card looks INTENTIONAL. It keeps its baseline and
 *     its day labels (so nothing moves when the first payment lands) but draws
 *     no value gridline, no axis tick and no bar.
 *  3. Loading, empty and loaded occupy the same box, so the card never shifts.
 *  4. The reader can INTERROGATE it: hover or keyboard focus on any day reveals
 *     that day and its exact amount, and the series is available as text to a
 *     screen reader that never hovers anything.
 *  5. Every figure is formatted by a PINNED en-US/UTC formatter, so the server
 *     pass and the hydration pass cannot disagree — `rendersIdenticallyUnder`
 *     proves it rather than asserting it in a comment.
 *  6. The grow-in is progressive enhancement: the markup carries the FINAL
 *     geometry, so a reader with JS disabled, JS slow, or reduced motion sees
 *     the finished chart rather than an empty one.
 *
 * jsdom has no layout engine, so geometry is asserted through DECLARED values —
 * the shared height class, the inline height percentages — not measured pixels.
 * That is what is knowable here; real geometry is on the manual-verification
 * list. Reduced motion is likewise a stylesheet fact, so #6 reads the stylesheet.
 */
import { readFileSync } from 'fs'
import { join } from 'path'
import { act, fireEvent, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderToString } from 'react-dom/server'

jest.mock('next-intl', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@/test-utils/intlMock').intlModuleMock(),
)

import {
  BAR_ANIMATION_CLASS,
  VolumeTrendChart,
  tickLabel,
  tooltipLeft,
  type VolumeBucket,
} from '@/components/app/VolumeTrendChart'

const DAYS = [
  '2026-08-14',
  '2026-08-15',
  '2026-08-16',
  '2026-08-17',
  '2026-08-18',
  '2026-08-19',
  '2026-08-20',
]

const populated = (): VolumeBucket[] =>
  DAYS.map((date, i) => ({ date, volume_usd: (i + 1) * 10 }))

const allZero = (): VolumeBucket[] =>
  DAYS.map((date) => ({ date, volume_usd: 0 }))

/** The shape production is actually in: one settled day among six quiet ones. */
const oneBusyDay = (): VolumeBucket[] => {
  const buckets = allZero()
  buckets[3].volume_usd = 20
  return buckets
}

/**
 * Put focus on a slot the way a browser does. jsdom's `.focus()` moves
 * `document.activeElement` but never dispatches `focusin`, which is the event
 * React actually listens to — so drive both. The tests that exist to prove the
 * KEYBOARD path works use `userEvent.tab()` instead; this is for the ones where
 * focus is merely the cheapest way to open the tooltip.
 */
const focusSlot = (el: HTMLElement) => {
  act(() => {
    el.focus()
    fireEvent.focusIn(el)
  })
}

describe('with data', () => {
  it('renders one bar per bucket', () => {
    const { getAllByTestId, queryByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(getAllByTestId('volume-bar')).toHaveLength(7)
    expect(queryByTestId('volume-trend-empty')).not.toBeInTheDocument()
  })

  it('keeps a slot for a quiet day, so the axis stays continuous', () => {
    const { getAllByTestId, queryByTestId } = render(
      <VolumeTrendChart buckets={oneBusyDay()} loading={false} />,
    )

    // Seven slots, not one floating dot — every day still holds its place …
    expect(getAllByTestId('volume-day-slot')).toHaveLength(7)
    expect(getAllByTestId('volume-day-label')).toHaveLength(7)
    // … but only the day that settled anything draws a bar.
    expect(getAllByTestId('volume-bar')).toHaveLength(1)
    expect(queryByTestId('volume-trend-empty')).not.toBeInTheDocument()
  })

  it('gives a zero day its label and its slot but no bar', () => {
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={oneBusyDay()} loading={false} />,
    )

    const slots = getAllByTestId('volume-day-slot')
    // Aug 17 (index 3) is the only day with volume.
    expect(slots[3].querySelector('[data-testid="volume-bar"]')).not.toBeNull()
    for (const i of [0, 1, 2, 4, 5, 6]) {
      expect(slots[i].querySelector('[data-testid="volume-bar"]')).toBeNull()
    }
    // The baseline is what makes a zero day read as measured, not missing.
    expect(getAllByTestId('volume-baseline')).toHaveLength(1)
  })

  it('scales bar heights to the series peak, with the largest at the top', () => {
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    // Values are 10…70, so heights must be 1/7…7/7 of the plot.
    const heights = getAllByTestId('volume-bar').map((bar) =>
      parseFloat((bar as HTMLElement).style.height),
    )

    expect(heights).toHaveLength(7)
    expect(heights[6]).toBe(100) // the peak defines the top of the scale
    heights.forEach((h, i) => {
      // 4dp is what the markup carries — fixed precision so the server pass and
      // the hydration pass emit byte-identical strings.
      expect(h).toBeCloseTo(((i + 1) / 7) * 100, 3)
    })
    // Strictly increasing — proportional, never clamped flat.
    for (let i = 1; i < heights.length; i++) {
      expect(heights[i]).toBeGreaterThan(heights[i - 1])
    }
  })

  it('carries a short and a long day label, and lets CSS pick', () => {
    // The axis column leaves a ~29px slot at 320px, where "Aug 20" is ~29px —
    // seven of them ran together into one string. Below `sm` the label is the
    // day of the month alone. BOTH are in the markup and a media query hides
    // one: choosing in JS from a measured width would make the server pass and
    // the client pass disagree, which is the one thing this component cannot do.
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const first = getAllByTestId('volume-day-label')[0]
    const short = first.querySelector('.sm\\:hidden')
    const long = first.querySelector('.hidden')

    expect(short).toHaveTextContent(/^14$/)
    expect(long).toHaveTextContent(/^Aug 14$/)
    expect(long?.className).toContain('sm:inline')
  })

  it('labels every day and puts the peak at the top of the value axis', () => {
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(getAllByTestId('volume-day-label')).toHaveLength(7)

    // Three ticks, top to bottom: peak, midpoint, zero — pinned USD.
    const ticks = getAllByTestId('volume-axis-tick').map((el) => el.textContent)
    expect(ticks).toEqual(['$70', '$35', '$0'])
  })
})

describe('axis ticks', () => {
  it('never outgrows the axis column, at any magnitude', () => {
    // The column is 32px with 4px of padding — 28px of text, which is five
    // characters of DM Mono at the tick's 9px ceiling. A tick wider than that
    // eats into the day labels beside it, so the ceiling is the contract.
    for (const v of [
      0, 1, 61.2, 999, 999.5, 1000, 1234.56, 9999, 10_000, 125_400, 999_400,
      999_600, 1_500_000, 12_345_678,
    ]) {
      expect(tickLabel(v).length).toBeLessThanOrEqual(5)
    }

    expect(tickLabel(0)).toBe('$0')
    expect(tickLabel(61.2)).toBe('$61')
    expect(tickLabel(999)).toBe('$999')
    expect(tickLabel(1234.56)).toBe('$1.2K')
    expect(tickLabel(9999)).toBe('$10K') // NOT "$10.0K" — six characters
    expect(tickLabel(125_400)).toBe('$125K')
    expect(tickLabel(999_600)).toBe('$1.0M') // NOT "$1000K", same reason
    expect(tickLabel(12_345_678)).toBe('$12M')
  })

  it('abbreviates with arithmetic, so no ICU version can disagree about it', () => {
    // `notation: 'compact'` would reintroduce one layer down the exact risk this
    // component exists to avoid: pinning the LOCALE does not pin the ICU
    // VERSION, and Node's compact-decimal patterns need not match the browser's
    // — a mismatch that surfaces as a hydration error on the dashboard. Proven
    // rather than asserted: with `Intl.NumberFormat` removed entirely, the
    // abbreviated ticks still come out.
    const Real = Intl.NumberFormat
    ;(Intl as any).NumberFormat = function () {
      throw new Error('tick abbreviation must not construct an ICU formatter')
    }
    try {
      expect(tickLabel(1234.56)).toBe('$1.2K')
      expect(tickLabel(12_345_678)).toBe('$12M')
    } finally {
      ;(Intl as any).NumberFormat = Real
    }
  })
})

describe('empty state', () => {
  it('renders the explanatory copy and no chart marks when every day is zero', () => {
    const { getByTestId, queryAllByTestId, queryByTestId } = render(
      <VolumeTrendChart buckets={allZero()} loading={false} />,
    )

    expect(getByTestId('volume-trend-empty')).toBeInTheDocument()
    // No bar, and specifically no value gridline — an empty axis with floating
    // gridlines is exactly the "looks broken" failure this card must avoid.
    expect(queryAllByTestId('volume-bar')).toHaveLength(0)
    expect(queryAllByTestId('volume-gridline')).toHaveLength(0)
    // An axis reading "$0 / $0 / $0" is noise, not information.
    expect(queryAllByTestId('volume-axis-tick')).toHaveLength(0)
    expect(queryByTestId('volume-trend-skeleton')).not.toBeInTheDocument()
  })

  it('keeps the baseline and the day labels so nothing shifts when data arrives', () => {
    const { getByTestId, getAllByTestId } = render(
      <VolumeTrendChart buckets={allZero()} loading={false} />,
    )

    expect(getByTestId('volume-baseline')).toBeInTheDocument()
    expect(getAllByTestId('volume-day-label')).toHaveLength(7)
  })

  it('treats a missing series as empty rather than rendering a wrong chart', () => {
    const { getByTestId, queryAllByTestId } = render(
      <VolumeTrendChart buckets={null} loading={false} />,
    )

    expect(getByTestId('volume-trend-empty')).toBeInTheDocument()
    expect(queryAllByTestId('volume-bar')).toHaveLength(0)
  })
})

describe('no layout shift', () => {
  const HEIGHT = 'h-32' // the chart is a supporting detail, not the subject

  it('gives loading, empty and populated states the same declared height', () => {
    // Scope each query to its OWN container: all three renders share one
    // document within a single test, so a document-wide query would match all
    // of them at once.
    const heightOf = (ui: React.ReactElement) => {
      const { container } = render(ui)
      const frame = container.querySelector('[data-testid="volume-trend-frame"]')
      expect(frame).not.toBeNull()
      return (frame as HTMLElement).className
    }

    const loading = heightOf(<VolumeTrendChart buckets={null} loading />)
    const empty = heightOf(<VolumeTrendChart buckets={allZero()} loading={false} />)
    const full = heightOf(<VolumeTrendChart buckets={populated()} loading={false} />)

    expect(loading).toContain(HEIGHT)
    expect(empty).toContain(HEIGHT)
    expect(full).toContain(HEIGHT)
  })

  it('renders a skeleton while loading, never a blank box', () => {
    const { getByTestId } = render(<VolumeTrendChart buckets={null} loading />)
    expect(getByTestId('volume-trend-skeleton')).toBeInTheDocument()
  })
})

describe('tooltip', () => {
  it('reveals the day and its amount on hover, and hides it again on leave', async () => {
    const user = userEvent.setup()
    const { getAllByTestId, queryByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(queryByTestId('volume-tooltip')).not.toBeInTheDocument()

    const slots = getAllByTestId('volume-day-slot')
    await user.hover(slots[3]) // 2026-08-17, $40

    const tip = getByTestId('volume-tooltip')
    expect(tip).toHaveTextContent('Aug 17')
    expect(tip).toHaveTextContent('$40.00')

    await user.unhover(slots[3])
    expect(queryByTestId('volume-tooltip')).not.toBeInTheDocument()
  })

  it('reveals the same tooltip when a reader TABS to the chart', async () => {
    // A chart reachable only by mouse is not reachable at all for some readers,
    // so this one drives the real keyboard path rather than a synthetic focus.
    const user = userEvent.setup()
    const { getAllByTestId, queryByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const slots = getAllByTestId('volume-day-slot')

    await user.tab()
    expect(slots[0]).toHaveFocus() // 2026-08-14, $10
    const tip = getByTestId('volume-tooltip')
    expect(tip).toHaveTextContent('Aug 14')
    expect(tip).toHaveTextContent('$10.00')

    // Tab again and focus leaves the chart entirely — the seven days are ONE
    // stop, not seven, so a reader passing by pays for one. The tooltip goes
    // with the focus.
    await user.tab()
    expect(slots[0]).not.toHaveFocus()
    expect(queryByTestId('volume-tooltip')).not.toBeInTheDocument()
  })

  it('walks the series with the arrow keys, one tab stop for seven days', async () => {
    const user = userEvent.setup()
    const { getAllByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const slots = getAllByTestId('volume-day-slot')
    // Roving tabindex: exactly one slot is in the tab order, and it is a
    // FIXED one, so the server pass ships a chart that can be tabbed into.
    expect(slots.map((s) => s.getAttribute('tabindex'))).toEqual([
      '0', '-1', '-1', '-1', '-1', '-1', '-1',
    ])

    await user.tab()
    await user.keyboard('{ArrowRight}')
    expect(slots[1]).toHaveFocus()
    expect(getByTestId('volume-tooltip')).toHaveTextContent('Aug 15')

    await user.keyboard('{ArrowLeft}{ArrowLeft}') // wraps past the start
    expect(slots[6]).toHaveFocus()
    expect(getByTestId('volume-tooltip')).toHaveTextContent('Aug 20')

    await user.keyboard('{Home}')
    expect(slots[0]).toHaveFocus()
    await user.keyboard('{End}')
    expect(slots[6]).toHaveFocus()
  })

  it('dismisses on Escape without moving focus away', async () => {
    const user = userEvent.setup()
    const { getAllByTestId, queryByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const slot = getAllByTestId('volume-day-slot')[0]
    await user.tab()
    expect(slot).toHaveFocus()
    expect(getByTestId('volume-tooltip')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(queryByTestId('volume-tooltip')).not.toBeInTheDocument()
    expect(slot).toHaveFocus() // Escape dismisses the tooltip, not the chart
  })

  it('is reachable on a quiet day too — a zero is a fact worth reading', () => {
    const { getAllByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={oneBusyDay()} loading={false} />,
    )

    focusSlot(getAllByTestId('volume-day-slot')[0])

    const tip = getByTestId('volume-tooltip')
    expect(tip).toHaveTextContent('Aug 14')
    expect(tip).toHaveTextContent('$0.00')
  })

  it('is held inside the plot at every bar, at every width', () => {
    // The tooltip is kept in bounds by a CSS `clamp()` rather than by measuring
    // anything, so the rule is a pure function and is tested as one — jsdom's
    // CSS parser mangles nested `calc()` inside `clamp()` on the way into
    // `style.left`, and a real browser is the only place the RENDERED box can
    // be checked (manual-verification list: 320 and 1440, first bar and last).
    //
    // Why not "pin the first and last bar, centre the rest": that reads as an
    // index rule but is really a width rule. At 320px the plot is ~206px, so a
    // 96px tooltip centred on bar 1 starts at −12px and one centred on bar 5
    // ends 12px past the right edge — both outside the card, both missed by an
    // index rule that only special-cases the ends.
    const asked = [0, 1, 2, 3, 4, 5, 6].map((i) => tooltipLeft(i, 7))

    for (const [i, left] of asked.entries()) {
      const centre = (((i + 0.5) * 100) / 7).toFixed(4)
      // Centre it on its own bar …
      expect(left).toContain(`calc(${centre}% - 3rem)`)
      // … but never left of the plot, nor past (plot width − tooltip width).
      expect(left).toBe(
        `clamp(0px, calc(${centre}% - 3rem), calc(100% - 6rem))`,
      )
    }

    // And the rendered tooltip really is positioned by that rule.
    const { getAllByTestId, getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )
    focusSlot(getAllByTestId('volume-day-slot')[0])
    expect(getByTestId('volume-tooltip').style.left).toContain('clamp(')
  })

  it('overlays rather than reflowing — the card is the same size either way', () => {
    // Scope to each render's OWN container: both renders share one document, so
    // a document-wide query would match the other one's slots too.
    const frameClass = (ui: React.ReactElement, focusIndex?: number) => {
      const { container } = render(ui)
      if (focusIndex !== undefined) {
        const slots = container.querySelectorAll('[data-testid="volume-day-slot"]')
        focusSlot(slots[focusIndex] as HTMLElement)
        expect(
          container.querySelector('[data-testid="volume-tooltip"]'),
        ).not.toBeNull() // the tooltip really is showing while we compare
      }
      const frame = container.querySelector('[data-testid="volume-trend-frame"]')
      return (frame as HTMLElement).className
    }

    const at_rest = frameClass(<VolumeTrendChart buckets={populated()} loading={false} />)
    const showing = frameClass(
      <VolumeTrendChart buckets={populated()} loading={false} />,
      3,
    )

    expect(showing).toBe(at_rest)
  })
})

describe('text alternative', () => {
  it('exposes every day and every value as readable text', () => {
    const { getByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const alt = getByTestId('volume-alt-text')
    for (const [i, label] of [
      'Aug 14', 'Aug 15', 'Aug 16', 'Aug 17', 'Aug 18', 'Aug 19', 'Aug 20',
    ].entries()) {
      expect(alt).toHaveTextContent(label)
      expect(alt).toHaveTextContent(`$${(i + 1) * 10}.00`)
    }
  })

  it('labels each focusable day with its own value, so tabbing narrates the series', () => {
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    const labels = getAllByTestId('volume-day-slot').map((s) =>
      s.getAttribute('aria-label'),
    )

    expect(labels[0]).toContain('Aug 14')
    expect(labels[0]).toContain('$10.00')
    expect(labels[6]).toContain('Aug 20')
    expect(labels[6]).toContain('$70.00')
  })
})

describe('animation is progressive enhancement', () => {
  const GLOBALS = readFileSync(
    join(__dirname, '../../globals.css'),
    'utf8',
  )

  it('ships the FINAL geometry in the markup, with nothing invisible awaiting JS', () => {
    // The server pass is the whole story here: whatever it emits is what a
    // reader with JS disabled or still-loading keeps looking at.
    const html = renderToString(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    // No start-state that only JS can clear.
    expect(html).not.toMatch(/opacity\s*:\s*0(?![.\d])/)
    // The peak bar is already at full height in the server markup.
    expect(html).toMatch(/height\s*:\s*100\.0000%/)
  })

  it('drives the grow-in from a CLASS, so a media query can switch it off', () => {
    // An inline `animation:` style — the pattern the loading skeleton uses —
    // cannot be overridden by `@media (prefers-reduced-motion)` without
    // `!important`. The class is what makes the guard below possible at all.
    const { getAllByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    for (const bar of getAllByTestId('volume-bar')) {
      expect(bar.className).toContain(BAR_ANIMATION_CLASS)
      expect(bar.style.animation).toBe('')
    }
  })

  it('disables the grow-in under prefers-reduced-motion', () => {
    // jsdom has no CSS cascade and its `matchMedia` is a stub that always
    // reports `matches: false`, so a media query cannot be *rendered* here —
    // the guarantee is read from the stylesheet instead. The rendered version
    // is on the manual-verification list (Playwright `emulateMedia`).
    expect(GLOBALS).toMatch(/@keyframes\s+rsendsBarGrow/)

    const guard = new RegExp(
      `@media\\s*\\(prefers-reduced-motion:\\s*reduce\\)\\s*\\{[^}]*\\.${BAR_ANIMATION_CLASS}\\b[^}]*\\{[^}]*animation:\\s*none[^}]*\\}`,
    )
    expect(GLOBALS).toMatch(guard)
  })

  it('declares no animation-fill-mode, so the resting state is the declared one', () => {
    // `forwards`/`backwards`/`both` would make the element render at a KEYFRAME
    // state outside the animation's run — i.e. the final state would stop being
    // the state the markup implies, which is the whole property above.
    const rule = GLOBALS.match(
      new RegExp(`\\.${BAR_ANIMATION_CLASS}\\s*\\{([^}]*)\\}`),
    )
    expect(rule).not.toBeNull()
    expect(rule![1]).not.toMatch(/animation-fill-mode/)
    expect(rule![1]).not.toMatch(/animation:[^;]*\b(forwards|backwards|both)\b/)
  })
})

describe('hydration determinism', () => {
  /**
   * Model the two environments a server pass and a browser pass actually differ
   * in: ambient locale and ambient timezone. Explicit `Intl` arguments win, so a
   * PINNED call site is immune — which is the point being proven.
   */
  function rendersIdenticallyUnder(ui: React.ReactElement): [string, string] {
    const RealDTF = Intl.DateTimeFormat
    const RealNF = Intl.NumberFormat
    const withAmbient = (locale: string, timeZone: string) => {
      ;(Intl as any).DateTimeFormat = function (l?: any, o?: any) {
        return new RealDTF(l ?? locale, { ...o, timeZone: o?.timeZone ?? timeZone })
      }
      ;(Intl as any).NumberFormat = function (l?: any, o?: any) {
        return new RealNF(l ?? locale, o)
      }
      try {
        return renderToString(ui)
      } finally {
        ;(Intl as any).DateTimeFormat = RealDTF
        ;(Intl as any).NumberFormat = RealNF
      }
    }
    return [
      withAmbient('en-US', 'UTC'),
      withAmbient('ja-JP', 'Asia/Tokyo'),
    ]
  }

  it('produces identical markup under any ambient locale/timezone', () => {
    const [server, client] = rendersIdenticallyUnder(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(server).toMatch(/Aug/) // fixture guard: labels really rendered
    expect(client).toBe(server)
  })

  it('pins the value axis too, not just the day labels', () => {
    // The axis ticks are numbers, so the risk here is the LOCALE (grouping and
    // currency placement), not the timezone: `¥70` or `70 $US` would be a text
    // mismatch on hydration exactly like a mis-timezoned day label.
    const [server, client] = rendersIdenticallyUnder(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(server).toContain('$70')
    expect(server).toContain('$35')
    expect(client).toBe(server)
  })
})
