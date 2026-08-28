// app/designTokens.ts
//
// Single source of truth for RSends palette and design tokens.
// All components import C from here. Do NOT redefine C inline.
//
// These values MIRROR the --rs-* custom properties in app/globals.css.
// They are literal hex on purpose and must stay that way: C values are
// handed to a <canvas> (see components/HeroGlobe.tsx, which passes
// C.terracotta / C.text as element attributes), and a canvas cannot parse
// `var()`. So this file cannot reference the CSS variables even though it
// used to claim it did.
//
// The duplication is not left to trust — app/__tests__/marketing/
// brandTokens.test.ts parses globals.css and asserts every pair matches.
// Change a colour in one file and the test names the other.

export const C = {
  // ── Surfaces ─────────────────────────────────────────────
  bg:      '#EFEEEA',   // --rs-paper
  surface: '#F7F6F3',   // --rs-surface
  card:    '#F7F6F3',

  // ── Text ─────────────────────────────────────────────────
  text:    '#0A0A0A',   // --rs-ink        17.05:1 on paper
  sub:     '#55534E',   // --rs-ink-muted   6.62:1 on paper
  dim:     '#55534E',

  // Foreground for dark surfaces only (ink CTA bands, video heroes, the
  // terracotta-deep navbar). The only sanctioned white. Never on paper.
  onDark:      '#FFFFFF',                  // --rs-on-dark
  onDarkMuted: 'rgba(255,255,255,0.72)',   // --rs-on-dark-muted
  onDarkLine:  'rgba(255,255,255,0.12)',   // --rs-on-dark-line (hairlines on dark)

  // ── Borders ──────────────────────────────────────────────
  // 1.18:1 against paper — decorative. Fine for dividers and card edges;
  // NOT sufficient as the only boundary of a control (WCAG 1.4.11 wants
  // 3:1 there), so an input needs a second cue as well.
  border:  '#DEDCD6',   // --rs-line

  // ── Brand accent ─────────────────────────────────────────
  // Two values, not interchangeable. See the note in globals.css.
  terracotta:      '#C8512C', // large text (>=24px) + graphics only
  terracottaDeep:  '#A8401F', // filled surfaces, links, small brand text
  terracottaWash:  '#F6E6DF', // subtle tints, active nav underline

  /** @deprecated Misnomer from the pre-terracotta palette — this was never
   *  purple. Kept as an alias so the 30-odd existing call sites keep working;
   *  use `terracotta` (or `terracottaDeep`) in new code. */
  purple:  '#C8512C',

  // ── Semantic status ──────────────────────────────────────
  green:   '#00D68F',
  red:     '#FF4C6A',
  amber:   '#FFB547',
  blue:    '#3B82F6',

  // ── Typography ───────────────────────────────────────────
  D:       'var(--font-display)',
  M:       'var(--font-mono)',
  S:       '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
} as const

export const EASE: [number, number, number, number] = [0.4, 0, 0.2, 1]
export const SPRING: [number, number, number, number] = [0.16, 1, 0.3, 1]

export type Palette = typeof C
