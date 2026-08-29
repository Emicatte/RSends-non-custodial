# RSends brand tokens

The palette for `apps/web`. Every ratio below is computed, not estimated, and
every one of them is re-derived from the tokens by
`apps/web/app/__tests__/marketing/brandTokens.test.ts` on each run — so this
document cannot quietly drift away from the code.

## Where the tokens live

Two files, deliberately, and a test that keeps them equal.

| File | Holds | Why |
|---|---|---|
| `apps/web/app/globals.css` (`:root`) | `--rs-*` custom properties | The source. CSS, Tailwind classes, and anything in a stylesheet reads these. |
| `apps/web/app/designTokens.ts` (`C`) | the same values as **literal hex** | `C` values are handed to a `<canvas>` — `HeroGlobe` passes `C.terracotta` / `C.text` as element attributes — and a canvas cannot parse `var()`. It has to be literal. |

`apps/web/tailwind.config.ts` maps class names (`bg-paper`, `text-ink-muted`,
`text-terracotta-deep`, …) onto the CSS variables. It defines no colour of its
own.

The duplication between the first two is real but not silent: the parity block
in `brandTokens.test.ts` asserts every `C.*` equals its `--rs-*` counterpart, so
changing one and forgetting the other fails the suite by name.

## The palette

| Token | Value | Use |
|---|---|---|
| `--rs-paper` | `#EFEEEA` | Page background. A warm-leaning **stone**, not a cream — see the note below. |
| `--rs-surface` | `#F7F6F3` | Raised cards, inputs, code blocks. |
| `--rs-ink` | `#0A0A0A` | Body text, headings. |
| `--rs-ink-muted` | `#55534E` | Secondary text. Warm grey; replaces every neutral grey. |
| `--rs-line` | `#DEDCD6` | Hairlines, dividers, card borders. **Decorative only** — see caveat. |
| `--rs-terracotta` | `#C8512C` | Large text (≥24px, or ≥18.66px bold) and graphics. Nothing smaller. |
| `--rs-terracotta-deep` | `#A8401F` | Filled surfaces, inline links, and any small text in brand colour. |
| `--rs-wash` | `#F6E6DF` | Subtle tints; the active nav underline. |
| `--rs-on-dark` | `#FFFFFF` | Text on genuinely dark surfaces only. |
| `--rs-on-dark-muted` | `rgba(255,255,255,0.72)` | Secondary text on dark surfaces. |
| `--rs-on-dark-line` | `rgba(255,255,255,0.12)` | Hairlines on dark surfaces. |

### The background is stone, not cream

`#EFEEEA` leans warm-grey. Do not drift it toward `#F4F1EA` or any beige. Warm
cream plus a terracotta accent is one of the most common generated-landing-page
palettes, and that resemblance is the specific thing this palette exists to
avoid.

### `--rs-on-dark` is the only sanctioned white

White text on the ink CTA band, over the hero videos, and on the terracotta
navbar is correct. It is a token rather than a literal because when it was
`#fff` scattered through components it also kept landing on light surfaces.
Never use it on `--rs-paper` or `--rs-surface`.

## Contrast

Measured with the WCAG 2.x relative-luminance formula.

| Foreground | Background | Ratio | Verdict |
|---|---|---|---|
| `#FFFFFF` | `#C8512C` terracotta | **4.50** | ⚠️ see below — this is 4.4975, **under** AA |
| `#FFFFFF` | `#A8401F` terracotta-deep | **6.14** | Passes AA and AAA-large. The filled-surface token. |
| `#C8512C` terracotta | `#EFEEEA` paper | **3.87** | Fails AA for body text. Passes the 3:1 bar for large text and graphics. |
| `#A8401F` terracotta-deep | `#EFEEEA` paper | **5.29** | Passes AA. Inline links, small brand text. |
| `#0A0A0A` ink | `#EFEEEA` paper | **17.05** | Body text. |
| `#55534E` ink-muted | `#EFEEEA` paper | **6.62** | Passes AA. Secondary text. |
| `#55534E` ink-muted | `#F7F6F3` surface | **7.11** | Passes AA. Secondary text on cards. |
| `#0A0A0A` ink | `#F7F6F3` surface | **18.32** | Body text on cards. |
| `#F6E6DF` wash | `#A8401F` terracotta-deep | **5.06** | The active-nav underline against the bar. |
| `#DEDCD6` line | `#EFEEEA` paper | **1.18** | ⚠️ decorative only — see caveat. |

### ⚠️ White on `#C8512C` does not meet AA

The true figure is **4.4975:1**. It rounds to 4.50 and is commonly quoted as
"exactly at the AA threshold", but 4.4975 < 4.5, so it does not meet AA at all —
only the 3:1 large-text and graphics bar applies.

This is the whole reason the palette carries two terracottas. `brandTokens.test.ts`
asserts the shortfall directly, so nobody can "fix" it by rounding.

### ⚠️ `--rs-line` cannot be a control's only boundary

At 1.18:1 against paper it is invisible to the contrast requirement. WCAG 1.4.11
asks for 3:1 for any boundary that is the **sole** means of identifying a
control. Dividers and card edges are fine. A text input bordered only in
`--rs-line` is not: give it a second cue, such as a `--rs-surface` fill that
contrasts with the page, or a darker border.

## Choosing between the two terracottas

The single question is **how big is the thing**.

| Situation | Token |
|---|---|
| Heading ≥24px, or ≥18.66px bold | `--rs-terracotta` |
| Icons, rules, globe arcs, charts, any non-text graphic | `--rs-terracotta` |
| Body text, labels, captions, nav items, anything <24px | `--rs-terracotta-deep` |
| Inline links at any size | `--rs-terracotta-deep` |
| A filled surface with text on it (buttons, the navbar, badges) | `--rs-terracotta-deep` |
| A filled surface with **no** text on it | either |

If you are unsure, `--rs-terracotta-deep` is always safe on paper and on
surface. `--rs-terracotta` is not.

## Radius

Three steps, on purpose. A single radius everywhere is the flattest tell of a
generated design.

| Step | Value | Applies to |
|---|---|---|
| control | `4px` | Buttons, inputs, badges, chips |
| card | `8px` | Cards, panels, dropdowns, code blocks |
| frame | `12px` | Device frames, media containers, large section blocks |

`50%` and `999px` remain for circles and true pills. The Tailwind aliases are
`rounded-control`, `rounded-card`, `rounded-frame`.

## Type

- **Display** — General Sans. The home H1 is `clamp(48px, 5.4vw, 76px)` at
  weight 600, tracking `-0.02em`. Section headings sit in the same band
  (`clamp(34px, 5vw, 64px)`, weight 600).
- **Body** — General Sans, unchanged.
- **DM Mono** — numbers, chain names, token symbols, addresses, hashes, status
  labels, and eyebrows. Nowhere else.

General Sans is fetched from the Fontshare CDN with `display=swap`, so it
arrives after first paint. `--font-display` therefore lists a metric-matched
fallback, `'General Sans Fallback'`, immediately after it: an `@font-face` over
local Arial/Helvetica with `size-adjust: 103.74%` (= 2272/2190, the measured
width ratio of the two faces on the hero string). Without it the headline
reflowed on swap and the home page scored CLS 0.0518; with it, 0.0020.

Two known problems this does not solve, both worth their own change: the face is
a render-blocking third-party `<link>` with no `next/font` and no self-hosting,
and `globals.css` asks for weights 300 and 800 that the CDN URL never loads (so
those synthesise).
