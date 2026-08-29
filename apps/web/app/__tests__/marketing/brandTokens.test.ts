/**
 * Brand token guards.
 *
 * Two jobs, both mechanical:
 *
 *  1. CONTRAST — every colour pair the brand relies on is recomputed from the
 *     tokens themselves and checked against the ratio docs/brand-tokens.md
 *     promises. Nothing here hardcodes a ratio it did not calculate, so
 *     editing a token to something illegible fails the suite rather than
 *     quietly shipping.
 *
 *  2. PARITY — app/designTokens.ts duplicates the --rs-* values as literal hex
 *     (it must: those values are passed to a <canvas>, which cannot parse
 *     `var()`). The duplication is safe only while something checks it.
 *
 * Ratios use the WCAG 2.x relative-luminance formula.
 */
import fs from 'fs'
import path from 'path'
import { C } from '../../designTokens'

const GLOBALS = path.join(__dirname, '../../globals.css')

/** Pull the `:root` --rs-* declarations out of globals.css. */
function readCssTokens(css: string): Record<string, string> {
  const root = css.slice(css.indexOf(':root'))
  const out: Record<string, string> = {}
  for (const m of root.matchAll(/(--rs-[\w-]+)\s*:\s*([^;]+);/g)) {
    out[m[1]] = m[2].trim()
  }
  return out
}

function channel(v: number): number {
  const s = v / 255
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
}

function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h
  const [r, g, b] = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16))
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function contrast(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

const css = readCssTokens(fs.readFileSync(GLOBALS, 'utf8'))
const WHITE = '#FFFFFF'

describe('brand tokens — contrast', () => {
  // Every pair carries the ratio docs/brand-tokens.md states, and the reason
  // that ratio is the bar. `min` is what the usage actually requires.
  const PAIRS: Array<{
    name: string
    fg: string
    bg: string
    documented: number
    min: number
    why: string
  }> = [
    {
      name: 'white on terracotta',
      fg: WHITE,
      bg: css['--rs-terracotta'],
      documented: 4.5,
      // 4.4975 to four places. It reads as "4.50" rounded and is commonly
      // quoted as "exactly AA", but it lands just UNDER the 4.5 line and so
      // does not meet AA at all. Only the 3:1 large-text/graphics bar applies.
      min: 3.0,
      why: 'rounds to 4.50 but is 4.4975 — under AA, so never a filled surface for body text',
    },
    {
      name: 'white on terracotta-deep',
      fg: WHITE,
      bg: css['--rs-terracotta-deep'],
      documented: 6.14,
      min: 4.5,
      why: 'the filled-surface token: navbar, primary buttons, and their focus rings',
    },
    {
      name: 'terracotta on paper',
      fg: css['--rs-terracotta'],
      bg: css['--rs-paper'],
      documented: 3.87,
      min: 3.0,
      why: 'large text (>=24px / >=18.66px bold) and graphical objects only',
    },
    {
      name: 'terracotta-deep on paper',
      fg: css['--rs-terracotta-deep'],
      bg: css['--rs-paper'],
      documented: 5.29,
      min: 4.5,
      why: 'inline links and small text in brand colour',
    },
    {
      name: 'ink on paper',
      fg: css['--rs-ink'],
      bg: css['--rs-paper'],
      documented: 17.05,
      min: 4.5,
      why: 'body text',
    },
    {
      name: 'ink-muted on paper',
      fg: css['--rs-ink-muted'],
      bg: css['--rs-paper'],
      documented: 6.62,
      min: 4.5,
      why: 'secondary body text — the warm grey that replaced the neutral one',
    },
    {
      name: 'ink-muted on surface',
      fg: css['--rs-ink-muted'],
      bg: css['--rs-surface'],
      documented: 7.11,
      min: 4.5,
      why: 'secondary text on raised cards',
    },
    {
      name: 'terracotta-wash on terracotta-deep',
      fg: css['--rs-wash'],
      bg: css['--rs-terracotta-deep'],
      documented: 5.06,
      min: 3.0,
      why: 'the active-nav underline against the navbar surface',
    },
  ]

  it.each(PAIRS)('$name meets its documented ratio', ({ fg, bg, documented, min, why }) => {
    expect(fg).toBeDefined()
    expect(bg).toBeDefined()
    const actual = contrast(fg, bg)
    // The documented figure must be true (to 2dp) AND clear the bar the usage needs.
    expect(`${actual.toFixed(2)} (${why})`).toBe(`${documented.toFixed(2)} (${why})`)
    expect(actual).toBeGreaterThanOrEqual(min)
  })

  it('white on terracotta does NOT reach AA — the reason terracotta is never a filled surface for body text', () => {
    expect(contrast(WHITE, css['--rs-terracotta'])).toBeLessThan(4.5)
    expect(contrast(WHITE, css['--rs-terracotta-deep'])).toBeGreaterThanOrEqual(4.5)
  })

  it('terracotta is NOT usable as a small-text colour on paper', () => {
    // Guards the rule rather than trusting people to remember it: if someone
    // "fixes" the palette by lightening paper, this is the line that objects.
    expect(contrast(css['--rs-terracotta'], css['--rs-paper'])).toBeLessThan(4.5)
    expect(contrast(css['--rs-terracotta-deep'], css['--rs-paper'])).toBeGreaterThanOrEqual(4.5)
  })

  it('--rs-line is decorative only and is documented as such', () => {
    // Recorded, not asserted as "good": 1.18:1 cannot be the sole boundary of
    // a control. docs/brand-tokens.md carries the caveat.
    expect(contrast(css['--rs-line'], css['--rs-paper'])).toBeLessThan(3.0)
  })
})

describe('brand tokens — designTokens.ts mirrors globals.css', () => {
  const MIRRORED: Array<[keyof typeof C, string]> = [
    ['bg', '--rs-paper'],
    ['surface', '--rs-surface'],
    ['card', '--rs-surface'],
    ['text', '--rs-ink'],
    ['sub', '--rs-ink-muted'],
    ['dim', '--rs-ink-muted'],
    ['border', '--rs-line'],
    ['terracotta', '--rs-terracotta'],
    ['terracottaDeep', '--rs-terracotta-deep'],
    ['terracottaWash', '--rs-wash'],
    ['onDark', '--rs-on-dark'],
    ['onDarkMuted', '--rs-on-dark-muted'],
    ['onDarkLine', '--rs-on-dark-line'],
    ['purple', '--rs-terracotta'],
  ]

  // Whitespace inside rgba() is a formatting choice on each side, not a
  // colour difference — compare the values, not the typography.
  const norm = (v: string) => v.replace(/\s+/g, '').toUpperCase()

  it.each(MIRRORED)('C.%s === %s', (key, cssVar) => {
    expect(norm(String(C[key]))).toBe(norm(css[cssVar]))
  })

  it('C holds literal hex, never var() — canvas attributes cannot resolve it', () => {
    // HeroGlobe passes these straight to <rsends-globe accent=... ink=...>.
    for (const key of ['bg', 'surface', 'text', 'sub', 'border', 'terracotta', 'terracottaDeep']) {
      expect(String(C[key as keyof typeof C])).toMatch(/^#[0-9A-Fa-f]{6}$/)
    }
  })
})
