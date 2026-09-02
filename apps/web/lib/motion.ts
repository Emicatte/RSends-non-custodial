/**
 * Single source of truth for "entrance/scroll animations may run".
 *
 * Two rules, one query:
 *  - below `MOTION_BP_PX` (phones) nothing animates — the page renders and stays
 *    rendered;
 *  - `prefers-reduced-motion: reduce` disables the same animations at every width.
 *
 * The breakpoint is Tailwind's `md` (tailwind.config.ts defines no custom
 * `screens`, so the stock defaults apply) and matches the 768 already used by
 * `hooks/useIsMobile.ts`.
 *
 * IMPORTANT: this query is mirrored verbatim in `app/globals.css` (the
 * `.main-content` / `.rs-hero-*` block). CSS cannot import a TS constant, so the
 * two are kept in sync by convention — change one, change the other.
 *
 * Visibility must never depend on JavaScript: elements rest in their natural,
 * visible state and the animation is applied only as an override under this
 * query. Nothing here may be used to *hide* content.
 */
export const MOTION_BP_PX = 768

export const MOTION_QUERY =
  `(min-width: ${MOTION_BP_PX}px) and (prefers-reduced-motion: no-preference)` as const

/**
 * Scroll reveals are gated on reduced motion ALONE, at every width — they are
 * the one exception to the 768px floor above, and deliberately so.
 *
 * That floor exists because the animations it guards cost layout: the hero
 * entrance, the device showcase's 3D, Lenis' scroll hijacking. A reveal moves
 * `opacity`, `transform` and `filter` and nothing else, so it cannot shift a
 * box and cannot contribute to CLS. Keeping phones out of it bought no
 * stability and cost the page its rhythm below 768px.
 *
 * The no-JavaScript promise is unchanged and still does not live here: blocks
 * rest visible via `.rs-reveal { opacity: 1 }` in globals.css, and the hidden
 * state exists only inside a tween that is actually running.
 */
export const REVEAL_QUERY = '(prefers-reduced-motion: no-preference)' as const

/**
 * One rhythm for every reveal on every marketing page. Read by
 * `components/motion/useReveal.ts`; no call site may override a value here
 * (pinned by `app/__tests__/marketing/revealTiming.test.tsx`).
 *
 * `start` without an `end`, and no `scrub`, is the whole shape of the fix. A
 * scrubbed reveal maps progress onto scroll POSITION, so it is only resolved
 * once the element reaches its `end` — which was `top 40%`, better than half a
 * viewport after the element first appeared. A short heading got there before
 * the taller cards beneath it, which is what production reported: sharp
 * heading, blurred cards, both fully on screen. A fixed duration cannot do
 * that. `top 90%` then means "10% in from the bottom edge", and 450ms later the
 * block is done wherever the reader has scrolled to.
 */
export const REVEAL = {
  /** Fires when the element's top is 10% in from the bottom edge. */
  start: 'top 90%',
  /** Forward only. Nothing replays, nothing reverses. */
  toggleActions: 'play none none none',
  once: true,
  /** Seconds. Long enough to read as motion, short enough not to be waited on. */
  duration: 0.45,
  /** px of rise. Transform only — never top/height, which would cost layout. */
  y: 16,
  /** px of blur while in flight, sharpening to 0 as it lands. */
  blur: 8,
  /** Seconds per item within one group, so a grid row lands in DOM order. */
  stagger: 0.06,
  /** Ceiling on the accumulated stagger: the last card never visibly lags. */
  staggerCap: 0.24,
  /** Registered on `gsap` by useReveal, from the curve below. */
  easeName: 'rsReveal',
  /** cubic-bezier(0.16, 1, 0.3, 1) as the SVG path CustomEase wants. */
  easeCurve: 'M0,0 C0.16,1 0.3,1 1,1',
} as const
