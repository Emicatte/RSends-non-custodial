'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import { C } from '@/app/designTokens'
import { MetricCards } from '@/components/app/MetricCards'
import { PaymentsTable } from '@/components/app/PaymentsTable'
import { VolumeTrendChart } from '@/components/app/VolumeTrendChart'
import { WebhookCard } from '@/components/app/WebhookCard'
import { SuccessView } from '@/app/pay/[intentId]/_components/StatusViews'
import { useClientNow } from '@/hooks/useClientNow'
import {
  SHOWCASE_METRICS,
  SHOWCASE_PAY,
  SHOWCASE_PAYMENTS,
  SHOWCASE_VOLUME_SERIES,
  SHOWCASE_WEBHOOKS,
  showcaseDeliveries,
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
 * `MetricCards`, `PaymentsTable`, `WebhookCard` and `SuccessView` are the SAME
 * components /app and /pay render, fed from components/landing/showcaseFixture.
 * They carry their own `useTranslations`, so the frame contents localize with
 * the page — and, more to the point, a label that changes in the dashboard
 * changes here in the same commit. The previous version of this section was a
 * pair of PNGs, and the only thing keeping them true was somebody remembering.
 *
 * ── The sequence, and why the DOM is arranged the way it is
 *
 * Three states advance as the section scrolls: dashboard, payments, webhooks.
 * The PAYMENTS layer is in flow and the other two are absolutely positioned over
 * it. That is load-bearing, not incidental:
 *
 *   - the stack's height is the payments table's height, which is stable and
 *     fills the frame — no dead grey below the last row;
 *   - with no JS at all, the payments state is what renders, which IS the
 *     required degradation for <1024px and for reduced motion. The gate does
 *     not have to hide anything; it simply never runs.
 *
 * The phone does not animate with the sequence. It is the fixed counterpart to
 * the merchant surface, and moving both at once is noise.
 *
 * ── Motion gate
 *
 * `gsap.matchMedia` on its OWN query, not lib/motion's MOTION_QUERY: that one is
 * 768px and this section needs 1024. Below it there is no ScrollTrigger and no
 * pin at all — a pinned section is the most CLS-damaging thing that can go on
 * this page, and 390px is where that would cost most. The literal is written out
 * per the convention documented at globals.css:1146-1149 (CSS cannot import a TS
 * constant, and `var()` is illegal in a media condition).
 */

/** Its own query. See the note above before changing either half. */
const SEQUENCE_QUERY = '(min-width: 1024px) and (prefers-reduced-motion: no-preference)'

const STATES = ['dashboard', 'payments', 'webhooks'] as const
type State = (typeof STATES)[number]

/**
 * Reserved before anything initialises, and in the layer that is in flow, so the
 * box exists from the first paint. Inline rather than in a stylesheet: it has to
 * apply before any CSS has loaded, and it is what the jsdom test can see.
 */
const STAGE_MIN_HEIGHT = 560

/** The crossfade. Outgoing blurs and shrinks a touch; incoming reverses it. */
const FADE_MS = 240

function layerStyle(active: boolean): React.CSSProperties {
  return {
    opacity: active ? 1 : 0,
    filter: active ? 'blur(0px)' : 'blur(3px)',
    transform: active ? 'scale(1)' : 'scale(0.98)',
    transition: `opacity ${FADE_MS}ms ease, filter ${FADE_MS}ms ease, transform ${FADE_MS}ms ease`,
    // Never a focus or pointer target while faded out.
    pointerEvents: active ? undefined : 'none',
  }
}

export default function DeviceShowcase() {
  const t = useTranslations('showcase')
  const nowMs = useClientNow()
  const stageRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<State>('payments')

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const mm = gsap.matchMedia()
    mm.add(SEQUENCE_QUERY, () => {
      setState('dashboard')
      const trigger = ScrollTrigger.create({
        trigger: stage,
        start: 'center center',
        end: '+=180%',
        pin: true,
        pinSpacing: true,
        onUpdate: (self) => {
          const i = Math.min(STATES.length - 1, Math.floor(self.progress * STATES.length))
          setState(STATES[i])
        },
      })
      return () => {
        trigger.kill()
        // Back to the no-JS state, so tearing the sequence down across the
        // breakpoint leaves the same thing a phone gets rather than a blank.
        setState('payments')
      }
    })
    return () => mm.revert()
  }, [])

  return (
    <section className="rs-showcase" aria-labelledby="rs-showcase-heading">
      <style>{`
        .rs-showcase { width: 100%; padding: 104px 24px 48px; }
        .rs-showcase-head { max-width: 760px; margin: 0 auto 64px; text-align: center; }
        .rs-showcase-stage { position: relative; max-width: 1180px; margin: 0 auto; }
        /* The browser stops 260px short of the stage and the phone is 280px, so
           the overlap is a constant 20px at every desktop width — the arithmetic
           does not drift with the stage. That 20px lands in the empty right half
           of the actions cell, whose buttons are left-aligned. A full-width
           browser put the phone over the whole ACTIONS column.

           NOTE: no backticks anywhere in this block. It is a template literal,
           and one inside a CSS comment silently terminates the string — the
           parse error lands on the JSX below it and reads as unrelated. */
        .rs-showcase-browser { width: calc(100% - 260px); }
        .rs-showcase-screen { width: 100%; }
        .rs-showcase-phone { width: 280px; position: absolute; right: 0; bottom: -40px; }
        .rs-showcase-label--phone { position: absolute; right: 0; bottom: -68px; width: 280px; text-align: center; }
        /* The checkout Shell is min-height 100vh (app/pay/_components/payUi.tsx)
           — right on a phone, where the page IS the viewport. Inside a frame the
           FRAME is the viewport, so the height is scoped to this box instead.
           Without it the phone stretches to the full landing-page viewport and
           the card floats in the middle of an 800px tower.

           !important is load-bearing, not laziness: Shell sets both of these as
           INLINE styles, and an inline declaration outranks any stylesheet rule
           that is not important. Dropping it silently restores the 100vh. */
        /* The in-flow payments layer sets the height of the whole stack, so
           fixing it here fixes the frame for all three states. 560px shows the
           table header and roughly nine rows and then clips — which is what a
           dashboard table does inside a viewport, and which leaves no dead grey
           under the shorter dashboard and webhook states. The alternative, a
           frame as tall as twelve rows, is two thirds empty on the other two. */
        .rs-showcase-screen--payments { height: 560px; overflow: hidden; }
        .rs-showcase-pay { height: 430px; }
        .rs-showcase-pay > main {
          min-height: 100% !important;
          padding: 16px 14px !important;
        }
        /* Below the sequence breakpoint the phone stops overlapping and stacks
           under the browser window. Same literal as SEQUENCE_QUERY. */
        @media (max-width: 1023px) {
          .rs-showcase { padding: 72px 20px 40px; }
          .rs-showcase-head { margin-bottom: 44px; }
          .rs-showcase-browser { width: 100%; }
          .rs-showcase-phone { position: static; width: 280px; margin: 44px auto 0; }
          .rs-showcase-label--phone { position: static; width: auto; margin-top: 10px; }
          /* A dashboard is a desktop surface. Reflowing it into a phone-width
             column would show a truthful-but-useless two-column stub of the
             table — which is what /app/payments really does at 390px, inside
             its own overflow-x scroller. So the frame keeps its desktop layout
             and is scaled to fit, the way a device mockup is meant to work.
             zoom rather than transform scale, because zoom affects layout, so
             the parent box shrinks with it and no height has to be computed by
             hand. (No backticks — see the note higher up.) */
          .rs-showcase-screen { width: 1000px; zoom: 0.70; }
        }
        @media (max-width: 767px) {
          .rs-showcase-screen { width: 1000px; zoom: 0.34; }
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
        style={{ minHeight: STAGE_MIN_HEIGHT }}
      >
        <div className="rs-showcase-browser">
          <div className="rs-showcase-screen">
          <BrowserFrame url="app.rsends.io">
            {/* Payments is the in-flow layer — it sets the height. */}
            <div
              data-showcase-state="payments"
              className="rs-showcase-screen--payments"
              style={layerStyle(state === 'payments')}
            >
              <div style={{ padding: 20 }}>
                <PaymentsTable
                  records={SHOWCASE_PAYMENTS}
                  nowMs={nowMs}
                  canManage
                  onRepeat={() => {}}
                  onCancel={() => {}}
                />
              </div>
            </div>

            <div
              data-showcase-state="dashboard"
              style={{ ...layerStyle(state === 'dashboard'), position: 'absolute', inset: 0, padding: 20 }}
            >
              {/* Cards AND the trend chart, because the real dashboard has both
                  and four cards alone leave two thirds of the frame grey. */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <MetricCards metrics={SHOWCASE_METRICS} />
                <VolumeTrendChart buckets={SHOWCASE_VOLUME_SERIES} loading={false} />
              </div>
            </div>

            <div
              data-showcase-state="webhooks"
              style={{ ...layerStyle(state === 'webhooks'), position: 'absolute', inset: 0, padding: 20 }}
            >
              {/* Three endpoints — staging, ledger and prod — which is both what
                  a real integration looks like and what fills the frame. */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {SHOWCASE_WEBHOOKS.map((w) => (
                  <WebhookCard
                    key={w.webhook_id}
                    webhook={w}
                    fetchDeliveries={async (id) => showcaseDeliveries(nowMs, id)}
                    sendTest={async () => ({ status: 'ok', response_code: 200, message: '' })}
                  />
                ))}
              </div>
            </div>
          </BrowserFrame>
          </div>
          <DeviceLabel className="rs-showcase-label--browser">{t('merchantLabel')}</DeviceLabel>
        </div>

        <div className="rs-showcase-phone">
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

      <p
        style={{
          margin: '104px 0 0',
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
