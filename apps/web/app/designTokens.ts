// app/designTokens.ts
//
// Single source of truth for RSends palette and design tokens.
// All components import C from here. Do NOT redefine C inline.
//
// To change a color globally, edit this file. Do NOT edit Tailwind config
// for palette changes (those live in app/globals.css as CSS variables).
//
// These values MIRROR the --rs-* custom properties in app/globals.css, and
// they are literal hex on purpose: components/HeroGlobe.tsx hands them to a
// <canvas> as element attributes, and a canvas cannot parse `var()`. Change a
// colour here and change it in globals.css in the same edit.

export const C = {
  // ── Surfaces ─────────────────────────────────────────────
  bg:      '#EFEEEA',   // --rs-paper
  surface: '#F7F6F3',   // --rs-surface
  card:    '#F7F6F3',

  // ── Text ─────────────────────────────────────────────────
  text:    '#0A0A0A',
  sub:     'rgba(10,10,10,0.55)',
  dim:     'rgba(10,10,10,0.55)',

  // Foreground for dark surfaces only — today that is the terracotta-deep
  // marketing nav. Never on paper or surface.
  onDark:      '#FFFFFF',                  // --rs-on-dark
  onDarkMuted: 'rgba(255,255,255,0.72)',   // --rs-on-dark-muted

  // ── Borders ──────────────────────────────────────────────
  border:  'rgba(10,10,10,0.12)',

  // ── Brand accent ─────────────────────────────────────────
  // Two values. White on #C8512C is 4.4975:1 — it rounds to 4.50 but is UNDER
  // the AA line, so #C8512C stays on large text and graphics (the globe) and
  // #A8401F carries filled surfaces such as the nav bar, where white on it is
  // 6.14:1.
  purple:         '#C8512C',   // --rs-terracotta
  terracottaDeep: '#A8401F',   // --rs-terracotta-deep

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
