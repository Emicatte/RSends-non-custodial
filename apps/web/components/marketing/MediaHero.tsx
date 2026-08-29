import { C } from '@/app/designTokens'
import MeshHeroVideo from '@/components/pricing/MeshHeroVideo'
import TypewriterHeadline from '@/components/vision/TypewriterHeadline'

const HPAD = 'clamp(20px, 6vw, 96px)'

type MediaHeroProps = {
  eyebrow: string
  title: string
  subline: string
  videoSrc: string
  poster: string
  /** Section height. /vision keeps the full-viewport default; /team runs shorter. */
  minHeight?: string
  /** Vertical push of the content block. The default assumes a 100vh section
      (optical anchor ~56% down); shorter heroes need a smaller offset. */
  contentOffset?: string
}

/**
 * Shared dark full-bleed video hero for the marketing pages (/vision, /team),
 * incl. the no-flash pattern from the pricing / how-it-works mesh hero.
 * Typography and scrim are deliberately NOT parameterized: the pages reading
 * as a matched set is the point.
 */
export default function MediaHero({
  eyebrow,
  title,
  subline,
  videoSrc,
  poster,
  minHeight = '100vh',
  contentOffset = 'clamp(40px, 12vh, 120px)',
}: MediaHeroProps) {
  return (
    <section
      style={{
        position: 'relative',
        width: '100%',
        minHeight,
        display: 'flex',
        alignItems: 'center',
        overflow: 'hidden',
        background: '#0A0A0A',
      }}
    >
      <MeshHeroVideo src={videoSrc} poster={poster} />
      {/* Ink scrim at 0.50: brightest glyph-scale patch behind the text
          column measures ~gray-121 on the re-graded footage; composited it
          gives the 68%-white subline 5.7:1 (AA needs 4.5:1). */}
      <div
        aria-hidden="true"
        style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,12,0.50)', zIndex: 1 }}
      />
      <div
        style={{
          // Full-width, not the centered 1160px container: on wide screens
          // the block hugs the viewport gutter instead of drifting toward
          // the optical center with the container.
          width: '100%',
          position: 'relative',
          zIndex: 2,
          padding: `0 ${HPAD}`,
          // Static offset: optical anchor sits ~56% down instead of dead
          // center. Applied identically SSR/client, outside the typewriter's
          // sizing ghost, so the type cycle stays CLS-free.
          marginTop: contentOffset,
        }}
      >
        {/* Three levels, left-aligned: eyebrow / typed headline / subline */}
        <div style={{ maxWidth: 640 }}>
          <div
            style={{
              fontFamily: C.M,
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: '#E8A488',
              marginBottom: 18,
            }}
          >
            {eyebrow}
          </div>
          <TypewriterHeadline
            text={title}
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(38px, 4.6vw, 64px)',
              fontWeight: 400,
              lineHeight: 1.08,
              letterSpacing: '-0.5px',
              color: C.onDark,
              margin: 0,
            }}
            subline={subline}
            sublineStyle={{
              fontFamily: C.D,
              fontSize: 16.5,
              lineHeight: 1.6,
              color: C.onDarkMuted,
              // ~52ch in loaded General Sans; px so the box doesn't reflow
              // when the webfont swaps in (ch resolves against the fallback
              // font first).
              maxWidth: 500,
              margin: '20px 0 0',
            }}
          />
        </div>
      </div>
    </section>
  )
}
