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
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
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

  describe('the address bar', () => {
    it('shows where the dashboard actually lives', async () => {
      const { container } = await renderShowcase()
      const chrome = container.querySelector('[data-frame="browser"]')
      expect(chrome!.textContent).toContain('rsends.io/app')
    })

    it('does not invent a host', async () => {
      const { container } = await renderShowcase()
      // `app.rsends.io` is a fiction: it is in no deploy config, no CORS
      // allowlist and no redirect. The deployed path is rsends.io/app.
      expect(container.textContent).not.toContain('app.rsends.io')
    })

    it('names the same host in every locale — chrome, not copy', async () => {
      for (const locale of LOCALES) {
        currentLocale = locale
        const { container, unmount } = await renderShowcase()
        expect(container.textContent).toContain('rsends.io/app')
        unmount()
      }
      currentLocale = 'en'
    })

    it('is not announced to a screen reader', async () => {
      const { container } = await renderShowcase()
      const url = Array.from(container.querySelectorAll('span')).find(
        (el) => el.textContent === 'rsends.io/app',
      )
      expect(url).toBeDefined()
      // A decorative address bar that is not a link and cannot be navigated has
      // nothing to say to somebody who cannot see it — but the frame's contents
      // are the real product and stay in the tree.
      expect(url!.closest('[aria-hidden="true"]')).not.toBeNull()
      expect(
        container.querySelector('[data-frame="browser"]')!.getAttribute('aria-hidden'),
      ).toBeNull()
    })

    it('leaves no `app.rsends.io` anywhere in the web app or its message files', () => {
      // The four remaining hits repo-wide are backend config docstrings, a
      // validate_settings error string and two pytest fixtures — real
      // references to a host this frontend does not serve, and not ours to
      // rewrite. This sweep is scoped to apps/web for that reason.
      const root = resolve(__dirname, '../../..')
      const offenders: string[] = []
      const walk = (dir: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
          // `__tests__` is excluded because this file has to name the string it
          // is banning; `_archive` because a retired page is not shipped.
          if (
            entry.name === 'node_modules' ||
            entry.name === '.next' ||
            entry.name === '_archive' ||
            entry.name === '__tests__'
          )
            continue
          const full = join(dir, entry.name)
          if (entry.isDirectory()) walk(full)
          else if (/\.(tsx?|jsx?|json|mdx?|css)$/.test(entry.name)) {
            if (readFileSync(full, 'utf8').includes('app.rsends.io')) {
              offenders.push(full.slice(root.length + 1))
            }
          }
        }
      }
      walk(root)
      expect(offenders).toEqual([])
    })
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

  // ── The sidebar ────────────────────────────────────────────────────────
  //
  // Without a left rail the frame reads as "a page with charts" rather than as
  // an application, and the moving active state is the only thing that makes
  // the Dashboard → Payments advance legible. Each layer carries its own rail
  // with its own fixed active entry, so what is asserted per-layer is exactly
  // what a visitor sees in that state.

  it('renders the whole left rail, not a subset of it', async () => {
    const { container } = await renderShowcase()
    const items = Array.from(
      container.querySelectorAll('[data-showcase-state="dashboard"] [data-sidebar-item]'),
    ).map((el) => el.getAttribute('data-sidebar-item'))
    expect(items).toEqual(['dashboard', 'payments', 'webhooks', 'apiKeys', 'settings'])
  })

  it('invents no rail label — every one resolves from app.sidebar', async () => {
    const { container } = await renderShowcase()
    const real = messageValues('app.sidebar')
    const labels = Array.from(
      container.querySelectorAll('[data-showcase-state="dashboard"] [data-sidebar-item]'),
    ).map((el) => el.textContent?.trim() ?? '')

    expect(labels.length).toBeGreaterThan(0)
    for (const label of labels) expect(real).toContain(label)
  })

  it('carries both group headings', async () => {
    const { container } = await renderShowcase()
    const rail = container.querySelector('[data-showcase-state="dashboard"] [data-sidebar]')
    expect(rail).not.toBeNull()
    expect(rail!.textContent).toContain(enMessages.app.sidebar.overview)
    expect(rail!.textContent).toContain(enMessages.app.sidebar.management)
  })

  it('marks Dashboard active in the dashboard state', async () => {
    const { container } = await renderShowcase()
    const active = container.querySelector(
      '[data-showcase-state="dashboard"] [data-sidebar-item][data-active="true"]',
    )
    expect(active?.getAttribute('data-sidebar-item')).toBe('dashboard')
  })

  it('marks Payments active in the advanced state', async () => {
    const { container } = await renderShowcase()
    const active = container.querySelector(
      '[data-showcase-state="payments"] [data-sidebar-item][data-active="true"]',
    )
    expect(active?.getAttribute('data-sidebar-item')).toBe('payments')
  })

  // Both ends of the mapping are driven explicitly rather than read off the
  // mount. jsdom gives every element a zero-sized rect, so the progress
  // ScrollTrigger computes for an unscrolled document is not a meaningful
  // stand-in for "the section has not been reached yet" — what this pins is the
  // contract the component actually owns: early progress shows the dashboard,
  // late progress shows payments, and the rail moves with it.
  it('advances from the dashboard layer to the payments layer as it scrolls', async () => {
    const { container } = await renderShowcase()
    const trigger = ScrollTrigger.getAll().at(-1)
    expect(trigger).toBeDefined()

    const opacityOf = (state: string) =>
      container.querySelector<HTMLElement>(`[data-showcase-state="${state}"]`)!.style.opacity
    const advance = async (progress: number) => {
      await act(async () => {
        trigger!.vars.onUpdate!({ progress } as never)
      })
    }

    await advance(0)
    expect(opacityOf('dashboard')).toBe('1')
    expect(opacityOf('payments')).toBe('0')

    await advance(0.95)
    expect(opacityOf('dashboard')).toBe('0')
    expect(opacityOf('payments')).toBe('1')
  })

  // ── The four cards ─────────────────────────────────────────────────────
  //
  // `totalBalance` is not a slow field, it is a field this product cannot
  // have: RSends never holds funds, so a balance tile asserts custody. And
  // `activeClients` is a traction claim about the company, not an interface
  // metric, on a page shown to prospective partners.

  it('renders exactly the four cards the product has', async () => {
    const { container } = await renderShowcase()
    const keys = Array.from(
      container.querySelectorAll('[data-showcase-state="dashboard"] [data-metric-label]'),
    ).map((el) => el.getAttribute('data-metric-label'))
    expect(keys).toEqual([
      'volume24h',
      'transactions24h',
      'volume30d',
      'webhooksDelivered24h',
    ])
  })

  // ── The transactions the frame shows ───────────────────────────────────

  it('shows the recent-transactions table with the product columns', async () => {
    const { container } = await renderShowcase()
    const heads = Array.from(
      container.querySelectorAll('[data-showcase-state="dashboard"] table thead th'),
    ).map((el) => el.textContent?.trim())
    expect(heads).toEqual(
      (['time', 'type', 'amount', 'chain', 'status'] as const).map(
        (c) => enMessages.app.dashboard.recentTransactions[c],
      ),
    )
  })

  it('settles every demo payment on Base', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fixture = require('@/components/landing/showcaseFixture')
    expect(fixture.SHOWCASE_RECENT_TX.length).toBeGreaterThan(0)
    for (const row of fixture.SHOWCASE_RECENT_TX) expect(row.chainKey).toBe('base')
    for (const row of fixture.SHOWCASE_PAYMENTS) expect(row.chain).toBe('base')
  })

  // On the DATA and on the rendered output, not on the source text: the file
  // is allowed to say in a comment why USDT was taken out, and a grep over the
  // source cannot tell that apart from a row that still carries it.
  it('claims no USDT — every demo payment is USDC', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fixture = require('@/components/landing/showcaseFixture')
    const values = JSON.stringify([
      fixture.SHOWCASE_PAYMENTS,
      fixture.SHOWCASE_RECENT_TX,
      fixture.SHOWCASE_METRICS,
      fixture.SHOWCASE_PAY,
    ])
    expect(values).not.toMatch(/USDT/i)
    for (const row of fixture.SHOWCASE_PAYMENTS) expect(row.currency).toBe('USDC')
  })

  // ── Depth, and the flat fallback ───────────────────────────────────────

  it('puts both devices in one perspective space, on the shared parent', async () => {
    const { container } = await renderShowcase()
    const stage = container.querySelector<HTMLElement>('[data-showcase-stage]')!
    expect(stage.style.perspective).toMatch(/\d+px/)
    // A `perspective()` inside a device's own transform makes two independent
    // spaces, which reads as two stickers rather than one scene.
    for (const kind of ['browser', 'phone']) {
      const el = container.querySelector<HTMLElement>(`[data-device="${kind}"]`)!
      expect(el.style.transform).not.toMatch(/perspective\(/)
    }
  })

  it('keeps both devices under the 10deg subpixel-antialiasing ceiling', async () => {
    const { container } = await renderShowcase()
    for (const kind of ['browser', 'phone']) {
      const el = container.querySelector<HTMLElement>(`[data-device="${kind}"]`)!
      const deg = /rotateY\((-?[\d.]+)deg\)/.exec(el.style.transform)
      expect(deg).not.toBeNull()
      expect(Math.abs(Number(deg![1]))).toBeLessThanOrEqual(10)
      expect(Math.abs(Number(deg![1]))).toBeGreaterThan(0)
    }
  })

  it.each([
    ['reduced motion', REDUCED],
    ['390px', MOBILE],
  ])('renders both devices flat under %s', async (_label, viewport) => {
    setViewport(viewport)
    const { container } = await renderShowcase()
    for (const kind of ['browser', 'phone']) {
      const el = container.querySelector<HTMLElement>(`[data-device="${kind}"]`)!
      expect(el.style.transform).toBe('')
    }
    expect(
      container.querySelector<HTMLElement>('[data-showcase-stage]')!.style.perspective,
    ).toBe('')
  })

  it.each([
    ['390px', MOBILE],
    ['768px', { width: 768, reduced: false }],
    ['1440px', DESKTOP],
  ])('reserves its box at %s', async (_label, viewport) => {
    setViewport(viewport)
    const { container } = await renderShowcase()
    const stage = container.querySelector<HTMLElement>('[data-showcase-stage]')!
    expect(stage.style.minHeight).toMatch(/\d/)
  })

  describe('motion gate', () => {
    // The positive case first. Without it the two negatives below would pass
    // against a section that simply never animates, which is the failure mode
    // this whole block exists to catch.
    it('creates the sequence at 768px and above when motion is allowed', async () => {
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

    it('creates no ScrollTrigger below 768px', async () => {
      setViewport(MOBILE)
      const before = ScrollTrigger.getAll().length
      await renderShowcase()
      expect(ScrollTrigger.getAll().length).toBe(before)
    })

    // A pinned section is the most CLS-damaging thing that can go on this
    // page, and CLS here is already 0.37 before this section does anything.
    it('never pins', async () => {
      setViewport(DESKTOP)
      await renderShowcase()
      const trigger = ScrollTrigger.getAll().at(-1)
      expect(trigger!.vars.pin).toBeFalsy()
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

    it('shows no USDT on screen', async () => {
      const { container } = await renderShowcase()
      expect(container.textContent).not.toMatch(/USDT/i)
    })

    // RSends is non-custodial: it holds no funds, so a balance tile is not a
    // slow field, it is a claim the product cannot make.
    it('shows no balance tile', async () => {
      const { container } = await renderShowcase()
      expect(container.textContent).not.toMatch(/saldo\s+totale|total\s+balance/i)
    })

    it('makes no traction claim', async () => {
      const { container } = await renderShowcase()
      expect(container.textContent).not.toMatch(/clienti\s+attivi|active\s+clients/i)
    })

    it('leaves no English in the card labels', async () => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const m = require(`@/messages/${locale}.json`)
      const own = new Set<string>(Object.values(m.app.dashboard.metrics))
      const { container } = await renderShowcase()
      const rendered = Array.from(
        container.querySelectorAll('[data-showcase-state="dashboard"] [data-metric-label]'),
      ).map((el) => el.textContent?.trim() ?? '')

      expect(rendered).toHaveLength(4)
      for (const label of rendered) expect(own).toContain(label)
    })
  })

  // A sentence, unlike "Volume 24h", cannot legitimately be identical in five
  // languages — so it is the one that catches a catalog left at the English
  // placeholder. `deliveryRate` is deliberately excluded: "{rate}%" is the
  // same everywhere and pretending otherwise would be a fake assertion.
  it.each(LOCALES.filter((l) => l !== 'en'))(
    'translates the sub-label sentence in %s',
    (locale) => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const en = require('@/messages/en.json').app.dashboard.metrics
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const other = require(`@/messages/${locale}.json`).app.dashboard.metrics
      expect(typeof other.vsYesterday).toBe('string')
      expect(other.vsYesterday).not.toBe(en.vsYesterday)
    },
  )

  it.each(LOCALES)('carries every card label in %s', (locale) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const metrics = require(`@/messages/${locale}.json`).app.dashboard.metrics
    for (const key of ['volume24h', 'transactions24h', 'volume30d', 'webhooksDelivered24h', 'vsYesterday', 'deliveryRate']) {
      expect(typeof metrics[key]).toBe('string')
      expect(metrics[key]).not.toBe('')
    }
  })
})
