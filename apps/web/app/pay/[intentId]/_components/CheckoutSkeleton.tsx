'use client'

/**
 * CheckoutSkeleton — the loading state of the hosted checkout. Renders the
 * SAME CheckoutFrame slots as the live view with fixed-width shimmer
 * placeholders (pulse animates opacity only; no transition: all, no GSAP),
 * so the layout is identical when data lands. The slow-retry notice appears
 * after the initial fetch has been retrying for a while.
 */

import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { CheckoutFrame } from './CheckoutFrame'

function Placeholder({ width, height = 14 }: { width: number; height?: number }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width,
        height,
        borderRadius: 6,
        background: 'rgba(10,10,10,0.07)',
        animation: 'rsendsSkeletonPulse 1.4s ease-in-out infinite',
      }}
    />
  )
}

function Row({ left, right }: { left: number; right: number }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        minHeight: 26,
      }}
    >
      <Placeholder width={left} />
      <Placeholder width={right} />
    </div>
  )
}

export function CheckoutSkeleton({ slow }: { slow: boolean }) {
  const t = useTranslations('pay')

  return (
    <>
      <style>{`@keyframes rsendsSkeletonPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }`}</style>
      <CheckoutFrame
        header={<Placeholder width={140} height={16} />}
        amount={<Placeholder width={190} height={34} />}
        summary={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Row left={60} right={90} />
            <Row left={80} right={70} />
            <Row left={40} right={100} />
            <Placeholder width={220} height={12} />
          </div>
        }
        action={<Placeholder width={396} height={47} />}
        notice={
          slow ? (
            <p
              style={{
                margin: 0,
                fontFamily: C.D,
                fontSize: 12.5,
                color: C.sub,
                textAlign: 'center',
              }}
            >
              {t('loadingRetry')}
            </p>
          ) : null
        }
        footer={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Placeholder width={300} height={12} />
            <Placeholder width={240} height={12} />
          </div>
        }
      />
    </>
  )
}
