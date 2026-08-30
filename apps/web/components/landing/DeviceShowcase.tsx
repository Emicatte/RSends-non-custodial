'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import { C } from '@/app/designTokens'
import { AppSidebarView } from '@/components/app/AppSidebarView'
import { MetricCards } from '@/components/app/MetricCards'
import { PaymentsTable } from '@/components/app/PaymentsTable'
import { RecentTransactionsTable } from '@/components/app/RecentTransactionsTable'
import { VolumeTrendChart } from '@/components/app/VolumeTrendChart'
import { SuccessView } from '@/app/pay/[intentId]/_components/StatusViews'
import { useClientNow } from '@/hooks/useClientNow'
import { MOTION_QUERY } from '@/lib/motion'
import {
  SHOWCASE_METRICS,
  SHOWCASE_PAY,
  SHOWCASE_PAYMENTS,
  SHOWCASE_RECENT_TX,
  SHOWCASE_VOLUME_SERIES,
} from '@/components/landing/showcaseFixture'
import { BrowserFrame } from './frames/BrowserFrame'
import { PhoneFrame } from './frames/PhoneFrame'

gsap.registerPlugin(ScrollTrigger)

/**
 * The two real surfaces, in the frames that match how each is used: the merchant
 * dashboard in a browser window, the payer's checkout on a phone. The frames and
 * the two labels carry the role separation, so no body copy has to explain it.
 *
 * ── Everything in these frames is the product, not a picture of it
 *
 * `AppSidebarView`, `MetricCards`, `VolumeTrendChart`, `RecentTransactionsTable`,
 * `PaymentsTable` and `SuccessView` are the SAME components /app and /pay
 * render, fed from components/landing/showcaseFixture. They carry their own
 * `useTranslations`, so the frame contents localize with the page — and, more
 * to the point, a label that changes in the dashboard changes here in the same
 * commit. An earlier version of this section was a pair of PNGs, and one of
 * them still showed a `Copy link` action weeks after it had been renamed to
 * `Repeat`; the only thing keeping a picture true is somebody remembering.
 *
 * ── The sequence, and why the DOM is arranged the way it is
 *
 * Two states advance as the section scrolls: dashboard, then payments. The rail
 * is in BOTH, with its active entry moving between them — without that, the
 * change reads as the content being swapped rather than as somebody using the
 * application, and without the rail at all the frame reads as a page with
 * charts.
 *
 * Both layers are absolutely positioned inside a stack of EXPLICIT height. Not
 * the in-flow-tallest-layer trick this section used before: a height derived
 * from content is a height that moves when the content does, and this page
 * already carries CLS 0.37 from its hero. A fixed box cannot contribute.
 * `payments` is the state that renders with no JS at all, which IS the required
 * degradation below the motion gate.
 *
 * The phone does not animate with the sequence. It is the fixed counterpart to
 * the merchant surface, and moving both at once is noise.
 *
 * ── Motion gate
 *
 * `gsap.matchMedia` on the SHARED `MOTION_QUERY` (768px + no-preference), the
 * same gate every other scroll behaviour on this page uses. Below it there is
 * no ScrollTrigger, no 3D and no blur — the flat, stacked variant. And there is
 * NO PIN in any state: a pinned section is the most CLS-damaging thing that can
 * go on this page.
 */

/**
 * The side-by-side arrangement, which is NOT the motion gate. Below 1024 the
 * phone stacks under the window (see the stylesheet), and `translateZ` — whose
 * whole job is to put the phone in FRONT of the browser rather than merely on
 * top of it in 2D — has nothing to be in front of. Worse, pushing a stacked
 * phone toward the viewer scales it past its own layout box and it swallows
 * its caption. So the push is tied to the overlap, and the rotation is not.
 */
const OVERLAP_QUERY = '(min-width: 1024px) and (prefers-reduced-motion: no-preference)'

type State = 'dashboard' | 'payments'

/** Where the sequence flips. Past the midpoint of the section's own travel. */
const ADVANCE_AT = 0.5

/**
 * The stack's box, reserved before anything initialises and never derived from
 * content. Inline rather than in a stylesheet: it has to apply before any CSS
 * has loaded, and it is what the jsdom test can see. 560px shows the rail, the
 * cards, the chart and the first transactions, then clips — which is what a
 * dashboard does inside a viewport, and which is why the last row is cut by the
 * window edge rather than sitting above empty grey.
 */
const STAGE_MIN_HEIGHT = 620
const SCREEN_HEIGHT = 560

/** The crossfade. Outgoing blurs and shrinks a touch; incoming reverses it. */
const FADE_MS = 250

/**
 * Small angles, and a hard ceiling of 10deg on either device. Past that the
 * browser drops subpixel antialiasing on transformed elements and the mono text
 * in the table goes mushy — a cost this section pays at all only because what
 * is inside the frames is live DOM rather than a picture. `perspective` lives
 * on the SHARED parent, never inside a device's own transform: two
 * `perspective()` functions are two independent spaces, and two vanishing
 * points read as two stickers laid on a page rather than as one scene.
 */
const PERSPECTIVE = '2000px'
const BROWSER_ROTATION = 6
const PHONE_ROTATION = -8

function layerStyle(active: boolean): React.CSSProperties {
  return {
    position: 'absolute',
    inset: 0,
    opacity: active ? 1 : 0,
    filter: active ? 'blur(0px)' : 'blur(3px)',
    transform: active ? 'scale(1)' : 'scale(0.98)',
    transition: `opacity ${FADE_MS}ms ease, filter ${FADE_MS}ms ease, transform ${FADE_MS}ms ease`,
    // Never a focus or pointer target while faded out.
    pointerEvents: active ? undefined : 'none',
    overflow: 'hidden',
  }
}

export default function DeviceShowcase() {
  const t = useTranslations('showcase')
  const nowMs = useClientNow()
  const stageRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<State>('payments')
  // Drives the 3D and the cast shadow. False on the server, on a phone and
  // under reduced motion — so the flat variant is what renders when nothing
  // runs, rather than something that has to be undone.
  const [sequence, setSequence] = useState(false)
  const [overlap, setOverlap] = useState(false)

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const mm = gsap.matchMedia()
    mm.add(MOTION_QUERY, () => {
      setSequence(true)
      setState('dashboard')
      const trigger = ScrollTrigger.create({
        trigger: stage,
        // The section's own travel through the viewport. No pin, so the page
        // keeps scrolling normally and this box never changes size.
        start: 'top bottom',
        end: 'bottom top',
        onUpdate: (self) => {
          setState(self.progress >= ADVANCE_AT ? 'payments' : 'dashboard')
        },
      })
      return () => {
        trigger.kill()
        // Back to the no-JS state, so tearing the sequence down across the
        // breakpoint leaves the same thing a phone gets rather than a blank.
        setSequence(false)
        setState('payments')
      }
    })
    mm.add(OVERLAP_QUERY, () => {
      setOverlap(true)
      return () => setOverlap(false)
    })
    return () => mm.revert()
  }, [])

  return (
    <section className="rs-showcase" aria-labelledby="rs-showcase-heading">
      <style>{`
        .rs-showcase { width: 100%; padding: 104px 24px 48px; }
        .rs-showcase-head { max-width: 760px; margin: 0 auto 64px; text-align: center; }
        /* ── The one piece of arithmetic this section rests on

           The window is sized by its CONTENTS and the phone is anchored to the
           WINDOW, not to the stage. That inversion is what makes the overlap a
           constant instead of a number that drifts as the page gets wider.

           SCREEN_W = 1186 is not a taste decision. The payments table is 859px
           at its natural width; the rail is 211; the body pads 20 left and 96
           right. 211 + 20 + 859 + 96 = 1186. A window any narrower slices the
           ACTIONS column, which is exactly the "clipped mid-cell reads as
           broken" failure this section is not allowed to have. Re-measure and
           re-derive if a column is ever added.

           The 96px right pad is the other half of it: the phone crosses 80px
           into the window (250 wide, anchored 170 out), so content stays 16px
           clear of it before the rotation swings the near edge in.

           The stage is capped at 1356 = the window plus the phone's 170px of
           reach, so the pair is centred AS A PAIR. Centring the window alone
           and letting the phone hang off its right edge is what pushes the page
           into a horizontal scrollbar at every width below 1600.

           NOTE: no backticks anywhere in this block. It is a template literal,
           and one inside a CSS comment silently terminates the string — the
           parse error lands on the JSX below it and reads as unrelated. */
        .rs-showcase-stage { position: relative; margin: 0 auto; max-width: 1356px; }
        .rs-showcase-browser { width: fit-content; position: relative; }
        .rs-showcase-screen { width: 1186px; }
        .rs-showcase-phone { width: 250px; position: absolute; right: -170px; bottom: -50px; z-index: 2; }
        .rs-showcase-label--phone { position: absolute; right: -170px; bottom: -86px; width: 250px; text-align: center; }
        .rs-showcase-body { padding: 20px 96px 20px 20px; }
        .rs-showcase-body--flat { padding: 20px; }
        /* Responsive scale bands. The zoom goes on the STAGE, so the window,
           the phone and the gap between them all scale by the same factor and
           every number above stays in one coordinate system.

           Putting it on the screen instead is the trap: the 96px clearance is
           then in scaled units while the phone still crosses 80 REAL pixels, so
           the narrower the band the more of the reserved margin the phone eats,
           and the ACTIONS column starts getting sliced again at 1024.

           Each band takes the largest scale whose 1356px composition still fits
           the narrowest viewport in it (viewport minus the 48px section padding
           and a little slack), so the page never gains a horizontal scrollbar.
           zoom rather than transform:scale, because zoom affects layout — the
           parent box shrinks with it and no height has to be computed by hand.
           From 1440 up nothing is scaled and the dashboard text is native. */
        @media (min-width: 1232px) and (max-width: 1439px) {
          .rs-showcase-stage { zoom: 0.82; }
        }
        @media (min-width: 1024px) and (max-width: 1231px) {
          .rs-showcase-stage { zoom: 0.65; }
        }
        /* The checkout Shell is min-height 100vh (app/pay/_components/payUi.tsx)
           — right on a phone, where the page IS the viewport. Inside a frame the
           FRAME is the viewport, so the height is scoped to this box instead.
           Without it the phone stretches to the full landing-page viewport and
           the card floats in the middle of an 800px tower.

           !important is load-bearing, not laziness: Shell sets both of these as
           INLINE styles, and an inline declaration outranks any stylesheet rule
           that is not important. Dropping it silently restores the 100vh. */
        .rs-showcase-pay { height: 430px; }
        .rs-showcase-pay > main {
          min-height: 100% !important;
          padding: 16px 14px !important;
        }
        /* Below 1024 the phone stops overlapping and stacks under the window.
           Two devices side by side need room for two devices, and keeping them
           side by side down there means scaling the pair until the window is a
           postage stamp. Stacking also makes the occlusion rule structural
           rather than a set of paddings to be re-tuned whenever a column moves.

           This is NOT the motion gate. The sequence, the 3D and the crossfade
           all still run from 768 up (MOTION_QUERY in lib/motion.ts); only the
           side-by-side arrangement stops.

           And the zoom moves off the stage onto the WINDOW alone. Above 1024
           the two devices overlap, so they have to scale together or the
           clearance arithmetic stops holding. Down here they are stacked and
           independent — and a phone is a phone. Shrinking it to 29% of itself
           beside a shrunken desktop is a picture of two small things, not a
           phone beside a small screen. */
        @media (max-width: 1023px) {
          .rs-showcase-stage { max-width: none; zoom: 1; }
          .rs-showcase-screen { zoom: 0.60; }
          .rs-showcase-phone { position: static; width: 280px; margin: 60px auto 0; }
          .rs-showcase-browser { margin: 0 auto; }
          .rs-showcase-label--phone { position: static; width: auto; margin-top: 10px; }
          /* Nothing to cast onto once the phone is not over the window. */
          .rs-showcase-castshadow { display: none; }
          /* And nothing to keep clear on the right. */
          .rs-showcase-body { padding: 20px; }
        }
        /* Same literal as MOTION_QUERY in lib/motion.ts — CSS cannot import a
           TS constant, so the two are kept in step by convention, exactly as
           globals.css already does. Below it the section is flat and static. */
        @media (max-width: 767px) {
          .rs-showcase { padding: 72px 20px 40px; }
          .rs-showcase-head { margin-bottom: 44px; }
          /* A dashboard is a desktop surface. Reflowing it into a phone-width
             column would show a truthful-but-useless two-column stub of the
             table — which is what /app/payments really does at 390px, inside
             its own overflow-x scroller. So the frame keeps its desktop layout
             and is scaled to fit, the way a device mockup is meant to work.
             zoom rather than transform scale, because zoom affects layout, so
             the parent box shrinks with it and no height has to be computed by
             hand. (No backticks — see the note higher up.) */
          .rs-showcase-screen { zoom: 0.29; }
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

      <div
        ref={stageRef}
        className="rs-showcase-stage"
        data-showcase-stage=""
        style={{
          minHeight: STAGE_MIN_HEIGHT,
          // One space for both devices, so their vanishing lines converge.
          perspective: sequence ? PERSPECTIVE : undefined,
        }}
      >
        <div
          className="rs-showcase-browser"
          data-device="browser"
          style={{
            transform: sequence ? `rotateY(${BROWSER_ROTATION}deg)` : undefined,
            transformOrigin: 'left center',
          }}
        >
          <div className="rs-showcase-screen">
            <BrowserFrame url="app.rsends.io">
              <div style={{ position: 'relative', height: SCREEN_HEIGHT }}>
                <ShowcaseScreen
                  state="dashboard"
                  active={state === 'dashboard'}
                  flat={!sequence}
                >
                  {/* Cards, the trend chart AND the recent settlements, because
                      that is what the dashboard home is. The table runs past
                      the bottom edge on purpose: an application continues below
                      the fold, and a table that stops short of it reads as the
                      end of the page. */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <MetricCards metrics={SHOWCASE_METRICS} />
                    <VolumeTrendChart buckets={SHOWCASE_VOLUME_SERIES} loading={false} />
                    <RecentTransactionsTable rows={SHOWCASE_RECENT_TX} />
                  </div>
                </ShowcaseScreen>

                <ShowcaseScreen
                  state="payments"
                  active={state === 'payments'}
                  flat={!sequence}
                >
                  <PaymentsTable
                    records={SHOWCASE_PAYMENTS}
                    nowMs={nowMs}
                    canManage
                    onRepeat={() => {}}
                    onCancel={() => {}}
                  />
                </ShowcaseScreen>

                {/* The phone's shadow, cast ON the window rather than on the
                    page behind it — the detail that puts one device in front of
                    the other instead of merely on top of it. A child of the
                    frame, which sets overflow:hidden, so it cannot spill past
                    the window edge onto the background. */}
                {overlap && (
                  <div
                    aria-hidden="true"
                    data-cast-shadow=""
                    className="rs-showcase-castshadow"
                    style={{
                      position: 'absolute',
                      right: -46,
                      bottom: -30,
                      width: 190,
                      height: 400,
                      borderRadius: 42,
                      background: 'rgba(10,10,10,0.34)',
                      filter: 'blur(18px)',
                      pointerEvents: 'none',
                    }}
                  />
                )}
              </div>
            </BrowserFrame>
          </div>

          <DeviceLabel className="rs-showcase-label--browser">{t('merchantLabel')}</DeviceLabel>
          {/* Anchored to the WINDOW, not to the stage — see the arithmetic note
              in the stylesheet. The window is sized by its contents and moves
              with them; a phone pinned to the stage instead would drift away
              from the edge it is supposed to be crossing. */}
          <div
            className="rs-showcase-phone"
            data-device="phone"
            style={{
              // translateZ needs an ancestor's perspective to mean anything,
              // which is why the perspective is on the stage and this is here.
              // Without it the phone merely overlaps in 2D.
              transform: sequence
                ? `rotateY(${PHONE_ROTATION}deg)${overlap ? ' translateZ(110px)' : ''}`
                : undefined,
              transformOrigin: 'right center',
            }}
          >
            <PhoneFrame>
              <div className="rs-showcase-pay">
                <SuccessView
                  amount={SHOWCASE_PAY.amount}
                  currency={SHOWCASE_PAY.currency}
                  merchant={SHOWCASE_PAY.merchant}
                  chainId={SHOWCASE_PAY.chainId}
                  txHash={SHOWCASE_PAY.txHash}
                  payer={SHOWCASE_PAY.payer}
                />
              </div>
            </PhoneFrame>
          </div>
          <DeviceLabel className="rs-showcase-label--phone">{t('payerLabel')}</DeviceLabel>
        </div>

      </div>

      <p
        style={{
          margin: '128px 0 0',
          textAlign: 'center',
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
 * One state of the merchant surface: the real rail beside the real page body.
 * The rail is what makes this read as an application, and its moving active
 * entry is what makes the advance legible.
 */
function ShowcaseScreen({
  state,
  active,
  flat,
  children,
}: {
  state: State
  active: boolean
  /** No phone overlapping the right edge, so the body can use its full width. */
  flat: boolean
  children: React.ReactNode
}) {
  return (
    <div
      data-showcase-state={state}
      style={{ ...layerStyle(active), display: 'flex', background: '#f7f6f3' }}
    >
      <AppSidebarView activeKey={state} variant="inline" />
      <div
        className={flat ? 'rs-showcase-body rs-showcase-body--flat' : 'rs-showcase-body'}
        style={{ flex: 1, minWidth: 0 }}
      >
        {children}
      </div>
    </div>
  )
}

/** Technical microcopy, at the size the rest of the page uses for it. */
function DeviceLabel({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <p
      className={className}
      style={{
        margin: '14px 0 0',
        fontFamily: C.M,
        fontSize: 11,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: C.sub,
      }}
    >
      {children}
    </p>
  )
}
