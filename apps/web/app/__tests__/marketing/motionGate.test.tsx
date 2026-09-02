/**
 * The motion gate: the animations that cost layout run on desktop only, and
 * only when the user has not asked for reduced motion. Below 768px, or under
 * `prefers-reduced-motion: reduce`, they are not created at all — not
 * created-and-killed, not created with a no-op tween. That covers the hero
 * entrance (the CSS half, mirrored in globals.css), the device showcase's 3D
 * sequence and Lenis' smooth scrolling.
 *
 * Scroll REVEALS deliberately no longer sit behind this query — they are gated
 * on `REVEAL_QUERY`, which drops the width floor and keeps only the
 * reduced-motion half, because a reveal moves opacity/transform/filter and so
 * cannot shift a box. Their timing, their gating and their reduced-motion
 * behaviour are asserted in `marketing/revealTiming.test.tsx`; what this file
 * still owns is the relationship between the two queries, and the hero.
 *
 * The second, larger promise this file guards: content is never hidden by
 * JavaScript. Every element rests visible; the hidden starting state exists only
 * while an animation is actually running. A late, failed or disabled bundle must
 * leave readable content behind.
 *
 * What jsdom CANNOT prove (see the plan's manual-verification list): jsdom never
 * evaluates the `globals.css` media query — `identity-obj-proxy` stubs CSS
 * outright — so "the CSS entrance animation does not run on mobile" and "content
 * is visible with JS disabled" are checked by hand in a real browser. What is
 * asserted here is the JS half: which instances get created, and what the
 * rendered markup contains.
 */
import { render, screen } from '@testing-library/react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'
import SplitText from '@/components/motion/SplitText'
import { MOTION_BP_PX, MOTION_QUERY, REVEAL_QUERY } from '@/lib/motion'

// ── matchMedia stand-in ───────────────────────────────────────────────────
// jest.setup.ts installs a permanently-false matchMedia; these tests need a
// real answer, so they evaluate the query against a fake viewport. Only the
// features this app actually queries are implemented.
const realMatchMedia = window.matchMedia

/**
 * Strict on purpose: an unrecognised feature throws instead of quietly
 * answering `true`. framer-motion asks for the bare boolean `(prefers-reduced-motion)`
 * form, and a permissive default made it believe reduced motion was on — which
 * made these assertions pass against the very markup they exist to reject.
 */
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
    // Boolean form: matches for any value other than `no-preference`.
    recognised = true
    matches &&= reduced
  }

  if (!recognised) throw new Error(`motionGate stub: unhandled media query "${query}"`)
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
const MOBILE = { width: 375, reduced: false }

let fromTo: jest.SpyInstance

beforeEach(() => {
  fromTo = jest.spyOn(gsap, 'fromTo')
})

afterEach(() => {
  fromTo.mockRestore()
  ScrollTrigger.getAll().forEach((t) => t.kill())
  window.matchMedia = realMatchMedia
})

/** Each `gsap.fromTo(el, …, { scrollTrigger })` call is exactly one instance. */
const scrubbedTargets = () =>
  fromTo.mock.calls
    .filter(([, , to]) => to && typeof to === 'object' && 'scrollTrigger' in to)
    .map(([target]) => target)

function Reveal() {
  return (
    <ScrubReveal>
      <p className="rs-reveal">first</p>
      <p className="rs-reveal">second</p>
      <p className="rs-reveal">third</p>
    </ScrubReveal>
  )
}

function Cascade() {
  return (
    <ScrubCascade>
      <div className="rs-card">card one</div>
      <div className="rs-card">card two</div>
    </ScrubCascade>
  )
}

describe('the two queries', () => {
  it('gates layout-costing motion on both width and reduced motion', () => {
    // Decided deliberately: the gate is a media query, not a JS width check, so
    // the first paint is correct before any JS has run.
    expect(MOTION_QUERY).toBe(
      '(min-width: 768px) and (prefers-reduced-motion: no-preference)',
    )
    expect(MOTION_BP_PX).toBe(768) // Tailwind `md`, and hooks/useIsMobile.ts
  })

  it('gates reveals on reduced motion alone — the same query minus the floor', () => {
    // The difference between the two is exactly the width clause, and that is
    // the whole intent: a reveal cannot shift a box, so a phone gets one.
    expect(REVEAL_QUERY).toBe('(prefers-reduced-motion: no-preference)')
    expect(MOTION_QUERY).toBe(`(min-width: ${MOTION_BP_PX}px) and ${REVEAL_QUERY}`)
  })
})

describe('prefers-reduced-motion: reduce', () => {
  it.each([
    ['mobile width', 375],
    ['desktop width', 1440],
  ])('creates no ScrollTrigger instance at %s', (_label, width) => {
    setViewport({ width, reduced: true })
    render(
      <>
        <Reveal />
        <Cascade />
      </>,
    )

    expect(scrubbedTargets()).toHaveLength(0)
    expect(ScrollTrigger.getAll()).toHaveLength(0)
  })

  it('leaves the content rendered and visible', () => {
    setViewport({ width: 375, reduced: true })
    render(<Reveal />)

    const first = screen.getByText('first')
    expect(first).toBeVisible()
    expect(first.style.opacity).toBe('')
    expect(first.style.visibility).toBe('')
  })
})

describe('no reduced-motion preference', () => {
  // Both widths, because reveals are no longer desktop-only. The instance count
  // is not assertable here: `once: true` kills a trigger the moment it reaches
  // its end, and every jsdom rect is zero, so start and end coincide. See
  // marketing/revealTiming.test.tsx, which asserts the tween and its trigger
  // element instead.
  it.each([
    ['desktop', DESKTOP],
    ['mobile', MOBILE],
  ])('reveals each .rs-reveal on the element itself, on %s', (_label, vp) => {
    setViewport(vp)
    const { container } = render(<Reveal />)
    const items = Array.from(container.querySelectorAll('.rs-reveal'))

    expect(items).toHaveLength(3)
    expect(scrubbedTargets()).toEqual(items)
  })

  it.each([
    ['desktop', DESKTOP],
    ['mobile', MOBILE],
  ])('reveals each .rs-card on the card itself, on %s', (_label, vp) => {
    setViewport(vp)
    const { container } = render(<Cascade />)
    const cards = Array.from(container.querySelectorAll('.rs-card'))

    expect(cards).toHaveLength(2)
    expect(scrubbedTargets()).toEqual(cards)
  })
})

describe('rendered markup never depends on JS to become visible', () => {
  it.each([
    ['mobile', MOBILE],
    ['desktop', DESKTOP],
    ['reduced motion', { width: 1440, reduced: true }],
  ])('SplitText renders plain, unclipped, untransformed text on %s', (_label, vp) => {
    setViewport(vp)
    const { container } = render(<SplitText text="Your wallet stays yours" delay={0.15} />)

    // Every word is present, in order, in the markup itself — no word is parked
    // outside a clip box waiting for JS. (Words are separated visually by
    // `margin-right`, not by whitespace in the text; that is unchanged from the
    // previous implementation, so `textContent` runs them together.)
    expect(container.textContent).toBe('Yourwalletstaysyours')

    container.querySelectorAll<HTMLElement>('span').forEach((el) => {
      expect(el.style.opacity).not.toBe('0')
      expect(el.style.visibility).not.toBe('hidden')
      // `overflow: hidden` + a translated child is how the headline used to be
      // clipped out of its own box before framer-motion hydrated.
      expect(el.style.overflow).not.toBe('hidden')
      expect(el.style.transform).toBe('')
    })
  })

  it('hands each word its own stagger delay for the CSS to consume', () => {
    setViewport(DESKTOP)
    const { container } = render(<SplitText text="Your wallet stays yours" delay={0.15} />)

    // `--rs-hero-word-delay` is the only link between this component and the
    // `.rs-hero-word` rule in globals.css; it must stay named and formatted as
    // the stylesheet expects. Deliberately NOT `--rs-hero-delay`: custom
    // properties inherit, and `.rs-hero-rise` uses that name.
    const delays = Array.from(container.querySelectorAll<HTMLElement>('.rs-hero-word')).map(
      (el) => el.style.getPropertyValue('--rs-hero-word-delay'),
    )
    expect(delays).toEqual(['0.15s', '0.19s', '0.23s', '0.27s'])
  })

  // Mobile is deliberately NOT in this list any more: reveals run there now, so
  // a running tween legitimately parks a block at `autoAlpha: 0` for 450ms. The
  // promise that survives is the one that matters — no JavaScript, or a request
  // for reduced motion, and the content is simply there. (The no-JS half is the
  // `.rs-reveal { opacity: 1 }` base rule in globals.css, which jsdom cannot
  // evaluate; it is on the manual-verification list.)
  it.each([['reduced motion', { width: 1440, reduced: true }]])(
    'revealed sections render with no inline hidden state on %s',
    (_label, vp) => {
    setViewport(vp)
    const { container } = render(
      <>
        <Reveal />
        <Cascade />
      </>,
    )

    container.querySelectorAll<HTMLElement>('.rs-reveal, .rs-card').forEach((el) => {
      expect(el.style.opacity).not.toBe('0')
      expect(el.style.visibility).not.toBe('hidden')
      expect(el.style.transform).toBe('')
    })
    },
  )
})
