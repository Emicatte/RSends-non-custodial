'use client'

import { useEffect, useRef } from 'react'
import Image from 'next/image'
import { useTranslations } from 'next-intl'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { C } from '@/app/designTokens'
import { MOTION_QUERY } from '@/lib/motion'

gsap.registerPlugin(ScrollTrigger)

/* ─────────────────────────────────────────────────────────────────────────────
 * CAPTURE SPEC — read this before producing the two PNGs.
 *
 * Both slots ship empty on purpose. Nothing in this component may be a drawn
 * impression of the product: the whole point of the section is that the site
 * shows the real thing. Take the captures, drop them in, flip the two
 * constants below. Do not commit a mock.
 *
 * Rig: the `apps/web:verify` skill already drives the authed dashboard locally
 * against a stubbed backend (stub on 127.0.0.1:4545, forged next-auth cookie).
 * Use it — it avoids pointing a camera at production data.
 *
 * ── 1. public/showcase/dashboard.png ────────────────────────────────────────
 *   route      /en/app/payments
 *   viewport   1440 × 900, deviceScaleFactor 2  (output 2880 × 1800)
 *   theme      light, prefers-reduced-motion: reduce (so nothing is mid-fade)
 *   must show  the payment-intent list with at least 4 rows, one of them
 *              `paid`, one `pending`; the amount, token and chain columns; the
 *              status pill legible. Include the page heading, exclude the
 *              browser chrome (the frame here supplies it).
 *   must NOT   show a real merchant name, a real wallet address, a real
 *              intent id, or a real amount. Use the stub's fixtures and keep
 *              addresses in the 0x0000…0000 style. No API key, ever.
 *
 * ── 2. public/showcase/pay.png ──────────────────────────────────────────────
 *   route      /pay/<intent-id> served from the stub
 *   viewport   390 × 844, deviceScaleFactor 3  (output 1170 × 2532)
 *   theme      light, prefers-reduced-motion: reduce
 *   must show  amount + token, the chain name, and the connect-wallet control
 *              in its disconnected state. The checkout's 500 × 720 rendering
 *              floor is a frozen promise (docs/INTEGRATION_CONTRACT.md) — do
 *              not capture below it and then scale up.
 *   must NOT   show a connected wallet address, a real intent id, or a real
 *              merchant name.
 *
 * Both: PNG, then run through an optimiser. next/image has no `formats` entry
 * in next.config.mjs, so it serves WebP only — no AVIF — and the width/height
 * below are what reserve the space, so they must match the real pixel ratio.
 * ─────────────────────────────────────────────────────────────────────────── */

/** TODO(emilio): capture — set to '/showcase/dashboard.png' once it exists. */
const DASHBOARD_CAPTURE: string | null = null
/** TODO(emilio): capture — set to '/showcase/pay.png' once it exists. */
const PAY_CAPTURE: string | null = null

const DASHBOARD_W = 1440
const DASHBOARD_H = 900
const PAY_W = 390
const PAY_H = 844

/**
 * A capture slot. Renders the real screenshot when there is one and a plain
 * labelled placeholder when there is not — never an invented facsimile of the
 * product. The box has the final aspect ratio in both states, so dropping the
 * PNG in later cannot shift the page.
 */
function CaptureSlot({
  src, width, height, alt, label,
}: { src: string | null; width: number; height: number; alt: string; label: string }) {
  if (src) {
    return (
      <Image
        src={src}
        width={width}
        height={height}
        alt={alt}
        sizes="(max-width: 900px) 100vw, 50vw"
        style={{ display: 'block', width: '100%', height: 'auto' }}
      />
    )
  }
  return (
    <div
      role="img"
      aria-label={label}
      style={{
        width: '100%',
        aspectRatio: `${width} / ${height}`,
        background: C.surface,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <span
        style={{
          fontFamily: C.M,
          fontSize: 11,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: C.sub,
        }}
      >
        {label}
      </span>
    </div>
  )
}

/**
 * The two ends of a payment, side by side: the dashboard where the merchant
 * creates the request, and the page their customer opens to pay it. A stroke
 * runs between them — the same geometry as the hero line and the globe arcs.
 *
 * The frames are drawn in CSS. The screenshots are not, and are not shipped
 * until someone takes them (see the capture spec above).
 */
export default function DeviceShowcase() {
  const t = useTranslations('showcase')
  const root = useRef<HTMLElement | null>(null)

  useEffect(() => {
    // Same gate as every other animation here: nothing is created at all below
    // 768px or under prefers-reduced-motion, so the stroke simply rests drawn.
    const mm = gsap.matchMedia()
    mm.add(MOTION_QUERY, () => {
      const ctx = gsap.context(() => {
        gsap.fromTo(
          '.rs-showcase-path',
          { scaleX: 0 },
          {
            scaleX: 1,
            duration: 0.9,
            ease: 'power2.out',
            scrollTrigger: { trigger: root.current, start: 'top 78%', once: true },
          },
        )
      }, root)
      return () => ctx.revert()
    })
    return () => mm.revert()
  }, [])

  return (
    <section
      ref={root}
      style={{ width: '100%', padding: '96px 24px', background: C.bg }}
    >
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <h2
          style={{
            fontFamily: C.D,
            fontSize: 'clamp(34px, 5vw, 64px)',
            fontWeight: 600,
            letterSpacing: '-0.02em',
            lineHeight: 1.1,
            color: C.text,
            margin: '0 0 12px',
            maxWidth: 900,
          }}
        >
          {t('heading')}
        </h2>
        <p
          style={{
            fontFamily: C.D,
            fontSize: 17,
            lineHeight: 1.6,
            color: C.sub,
            margin: '0 0 56px',
            maxWidth: 620,
          }}
        >
          {t('subcopy')}
        </p>

        <div className="rs-showcase-grid">
          {/* Desktop frame — merchant dashboard */}
          <figure className="rs-showcase-desktop" style={{ margin: 0 }}>
            <div
              style={{
                borderRadius: 12,
                border: `1px solid ${C.border}`,
                background: C.surface,
                overflow: 'hidden',
              }}
            >
              {/* Window chrome, drawn not photographed */}
              <div
                aria-hidden="true"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '10px 12px',
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                {[0, 1, 2].map(i => (
                  <span
                    key={i}
                    style={{
                      width: 9, height: 9, borderRadius: '50%',
                      background: C.border, display: 'block',
                    }}
                  />
                ))}
              </div>
              <CaptureSlot
                src={DASHBOARD_CAPTURE}
                width={DASHBOARD_W}
                height={DASHBOARD_H}
                alt={t('dashboardAlt')}
                label={t('placeholder')}
              />
            </div>
            <figcaption
              style={{
                fontFamily: C.M, fontSize: 11, letterSpacing: '0.14em',
                textTransform: 'uppercase', color: C.sub, marginTop: 14,
              }}
            >
              {t('dashboardCaption')}
            </figcaption>
          </figure>

          {/* The payment path between the two ends. scaleX from a left origin,
              drawn once when the section comes into view. */}
          <div className="rs-showcase-connector" aria-hidden="true">
            <div
              className="rs-showcase-path"
              style={{ background: C.terracotta, transformOrigin: 'left center' }}
            />
          </div>

          {/* Phone frame — the payer's checkout */}
          <figure className="rs-showcase-phone" style={{ margin: 0 }}>
            <div
              style={{
                borderRadius: 12,
                border: `1px solid ${C.border}`,
                background: C.surface,
                overflow: 'hidden',
                padding: 8,
              }}
            >
              <div
                aria-hidden="true"
                style={{
                  width: 54, height: 5, borderRadius: 999,
                  background: C.border, margin: '2px auto 8px',
                }}
              />
              <div style={{ borderRadius: 8, overflow: 'hidden' }}>
                <CaptureSlot
                  src={PAY_CAPTURE}
                  width={PAY_W}
                  height={PAY_H}
                  alt={t('payAlt')}
                  label={t('placeholder')}
                />
              </div>
            </div>
            <figcaption
              style={{
                fontFamily: C.M, fontSize: 11, letterSpacing: '0.14em',
                textTransform: 'uppercase', color: C.sub, marginTop: 14,
              }}
            >
              {t('payCaption')}
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  )
}
