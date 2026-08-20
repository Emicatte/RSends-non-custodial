/**
 * The /app "Volume trend (7d)" card.
 *
 * Three properties, in the order they matter:
 *
 *  1. With data, every bucket becomes a bar — seven days in, seven bars out.
 *  2. With no data, the card looks INTENTIONAL. Production currently holds one
 *     transaction, so the empty state is the state this card is actually in;
 *     a chart that looks broken when empty is worse than "Chart coming soon".
 *     It keeps its baseline and its day labels (so nothing moves when the
 *     first payment lands) but draws no value gridlines, no bar and no lone
 *     floating point.
 *  3. Loading and loaded occupy the same box, so the card never shifts layout.
 *
 * Rendering is deterministic by construction: the component is a pure function
 * of its props with locale- and timezone-PINNED formatters, so the server pass
 * and the hydration pass cannot disagree. `rendersIdenticallyUnder` below
 * proves it rather than asserting it in a comment.
 *
 * jsdom has no layout engine, so #3 asserts the DECLARED height class shared by
 * both states, not a measured pixel box. That is what is knowable here; real
 * geometry is on the manual-verification list.
 */
import { render } from '@testing-library/react'
import { renderToString } from 'react-dom/server'

jest.mock('next-intl', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@/test-utils/intlMock').intlModuleMock(),
)

import {
  VolumeTrendChart,
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

describe('with data', () => {
  it('renders one bar per bucket', () => {
    const { getAllByTestId, queryByTestId } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(getAllByTestId('volume-bar')).toHaveLength(7)
    expect(queryByTestId('volume-trend-empty')).not.toBeInTheDocument()
  })

  it('renders a bar for a quiet day too, so the axis stays continuous', () => {
    // Today's real shape: one non-zero day among six quiet ones.
    const buckets = allZero()
    buckets[3].volume_usd = 20
    const { getAllByTestId, queryByTestId } = render(
      <VolumeTrendChart buckets={buckets} loading={false} />,
    )

    // Seven slots, not one floating dot.
    expect(getAllByTestId('volume-bar')).toHaveLength(7)
    expect(queryByTestId('volume-trend-empty')).not.toBeInTheDocument()
  })

  it('labels every day and shows the peak value', () => {
    const { getAllByTestId, getByText } = render(
      <VolumeTrendChart buckets={populated()} loading={false} />,
    )

    expect(getAllByTestId('volume-day-label')).toHaveLength(7)
    // Peak of the series (7 * 10), formatted as pinned USD.
    expect(getByText('$70')).toBeInTheDocument()
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
  const HEIGHT = 'h-60' // the 240px box the "Chart coming soon" placeholder held

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
})
