'use client'

import Image from 'next/image'
import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'

/**
 * The two real surfaces, in the frames that match how each one is used: the
 * merchant dashboard on a laptop, the payer's checkout on a phone. The frames
 * carry the role separation, so no body copy has to explain it.
 *
 * Both screenshots are captured by `scripts/capture-mockups.ts` against a stub
 * backend, never taken by hand — see that file for the command. Nothing here is
 * a drawn impression of the product: if a capture is missing, fix the capture.
 *
 * Two rules this component exists to keep:
 *
 *  - The bezels are CSS (border, radius, shadow), not images. Only the screen
 *    content is a raster asset, so the payload is the screenshots alone and the
 *    frames inherit the brand colours from `app/designTokens.ts`.
 *  - Every screen box declares its aspect ratio INLINE, before the bytes land.
 *    The images are below the fold at 390px and therefore lazy, and a lazy
 *    image in an unsized box is how a section like this earns a CLS
 *    regression. The inline declaration is also what makes the reservation
 *    visible to the jsdom test in app/__tests__/marketing/deviceShowcase.test.tsx —
 *    a stylesheet rule would be invisible there.
 *
 * Responsive behaviour is CSS, never a JS breakpoint. `page.tsx` still computes
 * its hero layout from `window.innerWidth` in an effect and that single flip is
 * ~0.317 of the page CLS at 390px; this section must not add a second one.
 * Same rule MarketingNav.tsx documents.
 */

/** Capture geometry. These are CSS pixels — the PNGs are 2x and 3x of them. */
const DASHBOARD_W = 1440
const DASHBOARD_H = 900
const PAY_W = 390
const PAY_H = 750

const DASHBOARD_SRC = '/mockups/dashboard.png'
const PAY_SRC = '/mockups/pay.png'

/** Device hardware reads as hardware: ink bezels against the warm stone page. */
const BEZEL = C.text
const SCREEN_BG = C.surface

export default function DeviceShowcase() {
  const t = useTranslations('showcase')

  return (
    <section className="rs-showcase" aria-labelledby="rs-showcase-heading">
      <style>{`
        .rs-showcase {
          width: 100%;
          padding: 96px 24px 40px;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .rs-showcase-head {
          width: 100%;
          max-width: 720px;
          text-align: center;
          margin-bottom: 56px;
        }
        .rs-showcase-devices {
          width: 100%;
          max-width: 1120px;
          display: grid;
          /* Roughly the ratio that lands both devices on a common baseline at a
             similar height: the laptop is 16:10 and the phone is ~1:1.9, and
             the lid is inset inside its column (LID_WIDTH_PCT). */
          grid-template-columns: minmax(0, 3.5fr) minmax(0, 1fr);
          align-items: end;
          gap: 56px;
        }
        /* Stacked below 900px, laptop first. The order is the source order, so
           nothing needs reordering here. */
        @media (max-width: 899px) {
          .rs-showcase { padding: 64px 20px 32px; }
          .rs-showcase-head { margin-bottom: 40px; }
          .rs-showcase-devices {
            grid-template-columns: minmax(0, 1fr);
            justify-items: center;
            gap: 48px;
          }
          .rs-showcase-phone { max-width: 260px; }
        }
      `}</style>

      <div className="rs-showcase-head">
        <h2
          id="rs-showcase-heading"
          style={{
            margin: 0,
            fontFamily: C.D,
            fontSize: 'clamp(30px, 4.4vw, 46px)',
            lineHeight: 1.12,
            letterSpacing: '-0.02em',
            fontWeight: 600,
            color: C.text,
          }}
        >
          {t('heading')}
        </h2>
        <p
          style={{
            margin: '18px 0 0',
            fontFamily: C.D,
            fontSize: 'clamp(15px, 1.4vw, 18px)',
            lineHeight: 1.5,
            color: C.sub,
          }}
        >
          {t('subheading')}
        </p>
      </div>

      <div className="rs-showcase-devices">
        <LaptopFrame>
          <Image
            src={DASHBOARD_SRC}
            alt={t('dashboardAlt')}
            width={DASHBOARD_W}
            height={DASHBOARD_H}
            sizes="(max-width: 899px) 92vw, 62vw"
            style={{ display: 'block', width: '100%', height: 'auto' }}
          />
        </LaptopFrame>

        <PhoneFrame>
          <Image
            src={PAY_SRC}
            alt={t('payAlt')}
            width={PAY_W}
            height={PAY_H}
            sizes="(max-width: 899px) 60vw, 20vw"
            style={{ display: 'block', width: '100%', height: 'auto' }}
          />
        </PhoneFrame>
      </div>

      <p
        style={{
          margin: '40px 0 0',
          fontFamily: C.M,
          fontSize: 11,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: C.sub,
        }}
      >
        {t('demoDataLabel')}
      </p>
    </section>
  )
}

/**
 * Laptop: a lid whose bezel is thicker at the bottom, over a base that is wider
 * than the lid — that overhang is what makes the shape read as a laptop rather
 * than as a bordered picture.
 *
 * The base is the full width of the column and the LID is inset, rather than the
 * lid being full width and the base overhanging it. Same proportions, but the
 * widest element defines the box, so nothing can stick out past the section
 * padding. The first version had it the other way round (base `width: 112%`,
 * `margin-left: -6%`) and pushed the document 24px wider than the viewport at
 * 768px — a horizontal scrollbar on the whole page, from a decorative strip.
 *
 * `aspectRatio` sits inline on the screen box so the space is reserved whether
 * or not the PNG has arrived, and so the jsdom test can see the reservation.
 */
const LID_WIDTH_PCT = 89

function LaptopFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="rs-showcase-laptop" style={{ width: '100%' }}>
      <div
        style={{
          width: `${LID_WIDTH_PCT}%`,
          margin: '0 auto',
          background: BEZEL,
          borderRadius: 14,
          padding: '10px 10px 18px',
          boxShadow: '0 24px 60px rgba(10,10,10,0.18), 0 2px 8px rgba(10,10,10,0.10)',
        }}
      >
        <div
          style={{
            aspectRatio: `${DASHBOARD_W} / ${DASHBOARD_H}`,
            borderRadius: 5,
            overflow: 'hidden',
            background: SCREEN_BG,
          }}
        >
          {children}
        </div>
      </div>
      <div
        style={{
          width: '100%',
          height: 11,
          background: BEZEL,
          borderRadius: '0 0 9px 9px',
          boxShadow: '0 10px 22px rgba(10,10,10,0.16)',
        }}
      />
    </div>
  )
}

/** Phone: one continuous bezel, a speaker slot, no notch cutout to fake. */
function PhoneFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="rs-showcase-phone" style={{ width: '100%' }}>
      <div
        style={{
          background: BEZEL,
          borderRadius: 34,
          padding: 9,
          boxShadow: '0 24px 60px rgba(10,10,10,0.18), 0 2px 8px rgba(10,10,10,0.10)',
        }}
      >
        <div
          style={{
            position: 'relative',
            aspectRatio: `${PAY_W} / ${PAY_H}`,
            borderRadius: 26,
            overflow: 'hidden',
            background: SCREEN_BG,
          }}
        >
          {children}
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: 9,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 52,
              height: 5,
              borderRadius: 3,
              background: BEZEL,
              opacity: 0.85,
            }}
          />
        </div>
      </div>
    </div>
  )
}
