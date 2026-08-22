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
