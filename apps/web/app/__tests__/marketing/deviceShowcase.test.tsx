/**
 * The landing page's device showcase renders the REAL dashboard and checkout
 * components against one fixture — not markup written for marketing, and not a
 * screenshot of the product.
 *
 * That is the whole point, so most of what is asserted here is that nothing in
 * the frames was authored for the shop window:
 *
 *   - every action label in the payments table resolves from `app.payments`
 *   - every metric card label resolves from `app.dashboard.metrics`
 *   - no EURC anywhere (it is in no backend registry and create-intent 422s it)
 *
 * The other half is the motion and layout contract: no ScrollTrigger below
 * 1024px or under reduced motion, and the box is reserved before the sequence
 * initialises. A pinned section is the most CLS-damaging thing that can be put
 * on this page, which is why it does not exist on the viewports where that
 * would cost most.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, render, type RenderResult } from '@testing-library/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import enMessages from '@/messages/en.json'

let currentLocale = 'en'

/** Resolve a dotted namespace ("app.payments") then a dotted key inside it. */
function lookup(messages: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>(
    (node, part) => (node == null ? undefined : (node as Record<string, unknown>)[part]),
    messages,
  )
}

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require(`@/messages/${currentLocale}.json`)
    const t = (key: string, values?: Record<string, unknown>) => {
      const value = lookup(messages, `${namespace}.${key}`)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key} in ${currentLocale}`)
      }
      return values
        ? value.replace(/\{(\w+)\}/g, (_, k) => String(values[k] ?? `{${k}}`))
        : value
    }
    return t
  },
}))

import DeviceShowcase from '@/components/landing/DeviceShowcase'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const

// ── matchMedia stand-in, same shape as motionGate.test.tsx ────────────────
const realMatchMedia = window.matchMedia

function evaluate(query: string, width: number, reduced: boolean): boolean {
  let recognised = false
  let matches = true

  const min = /\(min-width:\s*(\d+)px\)/.exec(query)
  if (min) {
    recognised = true
    matches &&= width >= Number(min[1])
  }
  const max = /\(max-width:\s*(\d+)px\)/.exec(query)
  if (max) {
    recognised = true
    matches &&= width <= Number(max[1])
  }
  if (/prefers-reduced-motion:\s*no-preference/.test(query)) {
    recognised = true
    matches &&= !reduced
  } else if (/prefers-reduced-motion/.test(query)) {
    recognised = true
    matches &&= reduced
  }

  if (!recognised) throw new Error(`deviceShowcase stub: unhandled media query "${query}"`)
  return matches
}

function setViewport({ width, reduced }: { width: number; reduced: boolean }) {
  window.matchMedia = ((query: string) => ({
    matches: evaluate(query, width, reduced),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

const DESKTOP = { width: 1440, reduced: false }
const MOBILE = { width: 390, reduced: false }
const REDUCED = { width: 1440, reduced: true }

// jsdom implements no window.scrollTo, and ScrollTrigger calls it while
// refreshing a pin — which it correctly does at desktop width. Nothing here
// asserts scroll position, so stub it rather than let every run log
// "Not implemented: window.scrollTo".
const realScrollTo = window.scrollTo
beforeAll(() => {
  window.scrollTo = (() => {}) as typeof window.scrollTo
})
afterAll(() => {
  window.scrollTo = realScrollTo
})

beforeEach(() => {
  currentLocale = 'en'
  setViewport(DESKTOP)
})

afterEach(() => {
  ScrollTrigger.getAll().forEach((t) => t.kill())
  window.matchMedia = realMatchMedia
})

/**
 * WebhookCard loads its deliveries in an effect, so a bare render() leaves a
 * pending state update and React warns. Flush it here rather than leaving the
 * warning in every run.
 */
async function renderShowcase(): Promise<RenderResult> {
  let result!: RenderResult
  await act(async () => {
    result = render(<DeviceShowcase />)
  })
  return result
}

/** Every string value under a namespace, for "did this come from the product?" */
function messageValues(path: string, locale = 'en'): Set<string> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const messages = require(`@/messages/${locale}.json`)
  const node = lookup(messages, path)
  const out = new Set<string>()
  const walk = (n: unknown) => {
    if (typeof n === 'string') out.add(n)
    else if (n && typeof n === 'object') Object.values(n).forEach(walk)
  }
  walk(node)
  return out
}

describe('DeviceShowcase', () => {
  it('renders both device frames', async () => {
    const { container } = await renderShowcase()
    expect(container.querySelector('[data-frame="browser"]')).not.toBeNull()
    expect(container.querySelector('[data-frame="phone"]')).not.toBeNull()
  })

  it('renders the demo-data caption', async () => {
    const { container } = await renderShowcase()
    expect(container.textContent).toContain(enMessages.showcase.demoDataLabel)
  })

  it('reserves an explicit height before the sequence initialises', async () => {
    const { container } = await renderShowcase()
    const stage = container.querySelector<HTMLElement>('[data-showcase-stage]')
    expect(stage).not.toBeNull()
    // Inline, so it applies before any stylesheet or JS — and so jsdom can see
    // it, which a stylesheet rule would not be.
    expect(stage!.style.minHeight).toMatch(/\d/)
  })

  it('takes its rows from the fixture module, not from inline literals', async () => {
    const source = readFileSync(
      resolve(__dirname, '../../../components/landing/DeviceShowcase.tsx'),
      'utf8',
    )
    expect(source).toMatch(/from '@\/components\/landing\/showcaseFixture'/)
    expect(source).not.toMatch(/intent_id\s*:/)
  })

  it('shows no raster or media element of the product', async () => {
    const { container } = await renderShowcase()
    expect(container.querySelectorAll('img')).toHaveLength(0)
    expect(container.querySelectorAll('video')).toHaveLength(0)
    expect(container.querySelectorAll('canvas')).toHaveLength(0)
  })

  it('fills the table with enough rows to reach the frame edge', async () => {
    const { container } = await renderShowcase()
    expect(
      container.querySelectorAll('table tbody tr').length,
    ).toBeGreaterThanOrEqual(10)
  })

  it('invents no action label — every one resolves from app.payments', async () => {
    const { container } = await renderShowcase()
    const real = messageValues('app.payments')
    const actions = Array.from(
      container.querySelectorAll('table tbody td:last-child button, table tbody td:last-child a'),
    ).map((el) => el.textContent?.trim() ?? '')

    expect(actions.length).toBeGreaterThan(0)
    for (const label of actions) expect(real).toContain(label)
  })

  it('invents no metric card — every label resolves from app.dashboard.metrics', async () => {
    const { container } = await renderShowcase()
    const real = messageValues('app.dashboard.metrics')
    const labels = Array.from(
      container.querySelectorAll('[data-showcase-state="dashboard"] [data-metric-label]'),
    ).map((el) => el.textContent?.trim() ?? '')

    expect(labels.length).toBeGreaterThan(0)
    for (const label of labels) expect(real).toContain(label)
  })

  describe('motion gate', () => {
    // The positive case first. Without it the two negatives below would pass
    // against a section that simply never animates, which is the failure mode
    // this whole block exists to catch.
    it('creates the sequence at 1024px and above when motion is allowed', async () => {
      setViewport(DESKTOP)
      const before = ScrollTrigger.getAll().length
      await renderShowcase()
      expect(ScrollTrigger.getAll().length).toBe(before + 1)
    })

    it('creates no ScrollTrigger under prefers-reduced-motion: reduce', async () => {
      setViewport(REDUCED)
      const before = ScrollTrigger.getAll().length
      await renderShowcase()
      expect(ScrollTrigger.getAll().length).toBe(before)
    })

    it('creates no ScrollTrigger below 1024px', async () => {
      setViewport(MOBILE)
      const before = ScrollTrigger.getAll().length
      await renderShowcase()
      expect(ScrollTrigger.getAll().length).toBe(before)
    })
  })

  describe.each(LOCALES)('in %s', (locale) => {
    beforeEach(() => {
      currentLocale = locale
    })

    it('resolves both device labels', async () => {
      const { container } = await renderShowcase()
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const m = require(`@/messages/${locale}.json`)
      expect(container.textContent).toContain(m.showcase.merchantLabel)
      expect(container.textContent).toContain(m.showcase.payerLabel)
    })

    it('claims no EURC', async () => {
      const { container } = await renderShowcase()
      expect(container.textContent).not.toMatch(/EURC/i)
    })
  })
})
