// app/designTokens.ts
//
// Single source of truth for RSends palette and design tokens.
// All components import C from here. Do NOT redefine C inline.
//
// To change a color globally, edit this file. Do NOT edit Tailwind config
// for palette changes (those live in app/globals.css as CSS variables which
// this file references for runtime consistency).

export const C = {
  // ── Surfaces ─────────────────────────────────────────────
  bg:      '#FAFAFA',
  surface: '#FFFFFF',
  card:    '#FFFFFF',

  // ── Text ─────────────────────────────────────────────────
  text:    '#0A0A0A',
  sub:     'rgba(10,10,10,0.55)',
  dim:     'rgba(10,10,10,0.55)',

  // ── Borders ──────────────────────────────────────────────
  border:  'rgba(10,10,10,0.12)',

  // ── Brand accent ─────────────────────────────────────────
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
