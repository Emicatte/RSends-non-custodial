/**
 * The reveal contract: WHEN a block starts resolving, and how long it takes.
 *
 * The defect this file exists to prevent: the reveal used to be scroll-SCRUBBED,
 * which means an element was only fully resolved once it reached the tween's
 * `end` — `top 40%` on the landing page. An element therefore had to travel
 * better than half a viewport AFTER appearing before it was sharp, and a tall
 * card finished long after the short heading above it. Reported from production
 * as "the heading is readable while the cards under it are still blurred".
 *
 * So the values below are the fix, and they are asserted rather than described:
 * a reveal is a fixed-duration tween that FIRES when the element is 10% in from
 * the bottom edge, plays once, and never tracks the wheel. Every section on
 * every marketing page reads them from one place — `lib/motion.ts` — and no call
 * site is allowed to override them, which the last test in this file enforces
 * mechanically rather than by convention.
 */
import fs from 'node:fs'
import path from 'node:path'

import { render, screen } from '@testing-library/react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'
import { REVEAL, REVEAL_QUERY } from '@/lib/motion'

// ── matchMedia stand-in ───────────────────────────────────────────────────
// jest.setup.ts installs a permanently-false matchMedia; these tests need a
// real answer, so they evaluate the query against a fake viewport. Same shape
// as marketing/motionGate.test.tsx, deliberately: an unrecognised feature
// throws instead of quietly answering `true`, because a permissive default
// makes these assertions pass against the very markup they exist to reject.
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
  } else if (/prefers-reduced-motion:\s*reduce/.test(query)) {
    recognised = true
    matches &&= reduced
  } else if (/prefers-reduced-motion/.test(query)) {
    recognised = true
    matches &&= reduced
  }

  if (!recognised) throw new Error(`revealTiming stub: unhandled media query "${query}"`)
  return matches
}

function setViewport({ width, reduced }: { width: number; reduced: boolean }) {
  window.matchMedia = ((query: string) => {
    const matches = evaluate(query, width, reduced)
    return {
      matches,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }
  }) as typeof window.matchMedia
}

const DESKTOP = { width: 1440, reduced: false }
const MOBILE = { width: 390, reduced: false }

let fromTo: jest.SpyInstance

beforeEach(() => {
  fromTo = jest.spyOn(gsap, 'fromTo')
})

afterEach(() => {
  fromTo.mockRestore()
  ScrollTrigger.getAll().forEach((t) => t.kill())
  window.matchMedia = realMatchMedia
})

/**
 * Every `gsap.fromTo(el, from, { scrollTrigger })` call is exactly one reveal.
 *
 * This, and not `ScrollTrigger.getAll()`, is how a created reveal is counted
 * here: under `once: true` the instance kills ITSELF the moment it reaches its
 * end, and in jsdom every rect is zero, so start and end collapse onto the same
 * scroll position and the trigger is gone before the assertion runs. Verified
 * directly — the same tween with `once` dropped leaves one live instance
 * behind, and so does the old scrubbed form. `getAll()` is therefore still a
 * sound way to assert that NO reveal was created, and useless for asserting
 * that one was.
 */
const revealCalls = () =>
  fromTo.mock.calls.filter(([, , to]) => to && typeof to === 'object' && 'scrollTrigger' in to)

function Reveal({ count = 3 }: { count?: number }) {
  return (
    <ScrubReveal>
      {Array.from({ length: count }, (_, i) => (
        <p key={i} className="rs-reveal">{`item ${i}`}</p>
      ))}
    </ScrubReveal>
  )
}

function Cascade({ count = 2 }: { count?: number }) {
  return (
    <ScrubCascade>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rs-card">{`card ${i}`}</div>
      ))}
    </ScrubCascade>
  )
}

describe('the shared tokens', () => {
  it('fires when the element is 10% in from the bottom edge, once, unscrubbed', () => {
    expect(REVEAL.start).toBe('top 90%')
    expect(REVEAL.toggleActions).toBe('play none none none')
    expect(REVEAL.once).toBe(true)
    // No `end`, no `scrub`: a reveal is a duration, not a scroll range. Those
    // two keys existing at all is what made the reveal late.
    expect(REVEAL).not.toHaveProperty('end')
    expect(REVEAL).not.toHaveProperty('scrub')
  })

  it('runs for 450ms on the agreed ease-out curve', () => {
    expect(REVEAL.duration).toBe(0.45)
    expect(REVEAL.easeName).toBe('rsReveal')
    // cubic-bezier(0.16, 1, 0.3, 1), as an SVG path for CustomEase.
    expect(REVEAL.easeCurve).toBe('M0,0 C0.16,1 0.3,1 1,1')
  })

  it('moves opacity, blur and 16px of rise — nothing that costs layout', () => {
    expect(REVEAL.y).toBe(16)
    expect(REVEAL.blur).toBe(8)
  })

  it('staggers 60ms per item and stops compounding at 240ms', () => {
    expect(REVEAL.stagger).toBe(0.06)
    expect(REVEAL.staggerCap).toBe(0.24)
  })

  it('is gated on reduced motion alone, at every width', () => {
    // Deliberately NOT MOTION_QUERY: that one carries a 768px floor, which kept
    // reveals off phones entirely. Reveals move opacity/transform/filter only,
    // so they cost no layout and belong on a phone too.
    expect(REVEAL_QUERY).toBe('(prefers-reduced-motion: no-preference)')
  })
})

describe('the tween built from them', () => {
  it('is a fixed-duration play-once tween with no scroll range', () => {
    setViewport(DESKTOP)
    render(<Reveal />)

    const [, from, to] = revealCalls()[0]
    expect(from).toMatchObject({ autoAlpha: 0, y: 16, filter: 'blur(8px)' })
    expect(to).toMatchObject({
      autoAlpha: 1,
      y: 0,
      filter: 'blur(0px)',
      duration: 0.45,
      ease: 'rsReveal',
    })
    expect(to.scrollTrigger).toMatchObject({
      start: 'top 90%',
      toggleActions: 'play none none none',
      once: true,
    })
    // The whole point. A scrubbed reveal cannot resolve before the element has
    // crossed the viewport, however early it starts.
    expect('scrub' in to.scrollTrigger).toBe(false)
    expect('end' in to.scrollTrigger).toBe(false)
  })

  it('registers the ease it names, rather than falling back to linear', () => {
    setViewport(DESKTOP)
    render(<Reveal />)

    // gsap.parseEase returns undefined for an unknown name and the tween then
    // runs on the default ease — the assertion above would still pass.
    expect(typeof gsap.parseEase(REVEAL.easeName)).toBe('function')
  })

  it('keys each trigger to the element itself, not to the wrapper', () => {
    setViewport(DESKTOP)
    const { container } = render(<Reveal />)
    const items = Array.from(container.querySelectorAll('.rs-reveal'))

    // A wrapper trigger reveals everything inside a tall section at once,
    // including blocks two viewports further down.
    expect(revealCalls().map(([, , to]) => to.scrollTrigger.trigger)).toEqual(items)
  })

  it('steps the delay 60ms per item and caps the group at 240ms', () => {
    setViewport(DESKTOP)
    render(<Reveal count={6} />)

    expect(revealCalls().map(([, , to]) => to.delay)).toEqual([0, 0.06, 0.12, 0.18, 0.24, 0.24])
  })

  it('orders a card grid the same way', () => {
    setViewport(DESKTOP)
    render(<Cascade count={5} />)

    // Cards sharing a grid row enter at the same scroll position, so the order
    // has to come from the delay. It used to come from per-index trigger
    // offsets whose start/end range was inverted, which collapsed the scrub to
    // nothing and made the cards snap.
    expect(revealCalls().map(([, , to]) => to.delay)).toEqual([0, 0.06, 0.12, 0.18, 0.24])
  })
})

describe('reveals now run on a phone', () => {
  it.each([
    ['ScrubReveal', <Reveal count={3} key="r" />, '.rs-reveal', 3],
    ['ScrubCascade', <Cascade count={2} key="c" />, '.rs-card', 2],
  ])('reveals every element at 390px for %s', (_label, node, selector, expected) => {
    setViewport(MOBILE)
    const { container } = render(node)
    const items = Array.from(container.querySelectorAll(selector as string))

    // The 768px floor used to leave phones with no reveal at all. A reveal
    // animates opacity/transform/filter only, so it cannot shift a box — there
    // was no stability to buy by excluding them.
    expect(items).toHaveLength(expected as number)
    expect(revealCalls().map(([, , to]) => to.scrollTrigger.trigger)).toEqual(items)
  })

  it('gives a phone the same timing as a desktop, not a variant of it', () => {
    setViewport(MOBILE)
    render(<Reveal count={2} />)
    const phone = revealCalls().map(([, from, to]) => [from, { ...to, scrollTrigger: to.scrollTrigger.trigger.className }])

    fromTo.mockClear()
    setViewport(DESKTOP)
    render(<Reveal count={2} />)
    const desktop = revealCalls().map(([, from, to]) => [from, { ...to, scrollTrigger: to.scrollTrigger.trigger.className }])

    expect(phone).toEqual(desktop)
  })
})

describe('prefers-reduced-motion: reduce', () => {
  it.each([
    ['desktop', 1440],
    ['phone', 390],
  ])('creates no trigger at all on %s', (_label, width) => {
    setViewport({ width, reduced: true })
    render(
      <>
        <Reveal />
        <Cascade />
      </>,
    )

    expect(revealCalls()).toHaveLength(0)
    expect(ScrollTrigger.getAll()).toHaveLength(0)
  })

  it('leaves every block in its final state — visible, sharp, unmoved', () => {
    setViewport({ width: 1440, reduced: true })
    const { container } = render(
      <>
        <Reveal />
        <Cascade />
      </>,
    )

    const blocks = container.querySelectorAll<HTMLElement>('.rs-reveal, .rs-card')
    expect(blocks).toHaveLength(5)
    blocks.forEach((el) => {
      expect(el).toBeVisible()
      expect(el.style.opacity).toBe('')
      expect(el.style.visibility).toBe('')
      expect(el.style.transform).toBe('')
      expect(el.style.filter).toBe('')
    })
    expect(screen.getByText('item 0')).toBeVisible()
  })
})

describe('no call site may override the rhythm', () => {
  /** Every .tsx under the two source roots, excluding the test tree itself. */
  function sources(dir: string, acc: string[] = []): string[] {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === '__tests__' || entry.name === 'node_modules') continue
        sources(full, acc)
      } else if (entry.name.endsWith('.tsx')) {
        acc.push(full)
      }
    }
    return acc
  }

  const WEB_ROOT = path.resolve(__dirname, '../../..')
  const FORBIDDEN = [
    'start',
    'end',
    'scrub',
    'duration',
    'ease',
    'y',
    'blur',
    'stagger',
    'startBase',
    'endBase',
  ]

  it('passes no timing prop to ScrubReveal or ScrubCascade anywhere', () => {
    const files = [
      ...sources(path.join(WEB_ROOT, 'app')),
      ...sources(path.join(WEB_ROOT, 'components')),
    ]
    const offenders: string[] = []

    for (const file of files) {
      const src = fs.readFileSync(file, 'utf8')
      const tag = /<Scrub(?:Reveal|Cascade)\b/g
      let m: RegExpExecArray | null
      while ((m = tag.exec(src))) {
        const close = src.indexOf('>', m.index)
        const props = src.slice(m.index, close === -1 ? src.length : close)
        for (const prop of FORBIDDEN) {
          if (new RegExp(`\\b${prop}\\s*=`).test(props)) {
            const line = src.slice(0, m.index).split('\n').length
            offenders.push(`${path.relative(WEB_ROOT, file)}:${line} → ${prop}=`)
          }
        }
      }
    }

    // One rhythm across the page means the values live in lib/motion.ts and
    // nowhere else. `scrub={0.5}` on sixteen call sites is how the landing page
    // ended up on a slower reveal than every other marketing page.
    expect(offenders).toEqual([])
  })

  it('finds the call sites at all, so the sweep above cannot pass by mistake', () => {
    const files = [
      ...sources(path.join(WEB_ROOT, 'app')),
      ...sources(path.join(WEB_ROOT, 'components')),
    ]
    const count = files.reduce(
      (n, f) => n + (fs.readFileSync(f, 'utf8').match(/<Scrub(?:Reveal|Cascade)\b/g)?.length ?? 0),
      0,
    )
    expect(count).toBeGreaterThan(15)
  })
})
