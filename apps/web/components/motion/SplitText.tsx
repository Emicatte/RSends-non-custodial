'use client'

/**
 * Per-word rise for the home hero headline.
 *
 * Deliberately CSS-only. The previous framer-motion version rendered every word
 * translated `y: 110%` inside an `overflow: hidden` box, which meant the served
 * HTML contained an empty headline until React hydrated — a blank frame on any
 * slow load, and a permanently empty headline if the bundle never arrived.
 *
 * Here the resting state IS the visible state: plain, untransformed, unclipped
 * text. The rise is layered on top by `.rs-hero-word` / `.rs-hero-word-clip` in
 * app/globals.css, which exist only inside the `MOTION_QUERY` media query — so
 * phones and reduced-motion users get static text, and no JavaScript is
 * involved in making any of it visible.
 *
 * The per-word stagger is dynamic (the word count comes from the text), so each
 * word carries its own delay as an inline custom property. When the media query
 * does not match, no rule reads it and it is inert.
 */
type Props = {
  text: string
  className?: string
  style?: React.CSSProperties
  /** delay (s) before the first word rises */
  delay?: number
  /** additional delay (s) per subsequent word */
  stagger?: number
}

export default function SplitText({ text, className, style, delay = 0, stagger = 0.04 }: Props) {
  return (
    <span className={className} style={{ display: 'inline-block', ...style }}>
      {text.split(' ').map((word, wi) => (
        <span
          key={wi}
          className="rs-hero-word-clip"
          style={{ display: 'inline-block', marginRight: '0.25em' }}
        >
          <span
            className="rs-hero-word"
            style={
              {
                display: 'inline-block',
                // toFixed keeps 0.15 + 1 * 0.04 out of the DOM as 0.19, not
                // 0.19000000000000003.
                '--rs-hero-word-delay': `${+(delay + wi * stagger).toFixed(4)}s`,
              } as React.CSSProperties
            }
          >
            {word}
          </span>
        </span>
      ))}
    </span>
  )
}
