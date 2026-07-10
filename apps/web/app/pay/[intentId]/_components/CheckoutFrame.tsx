'use client'

/**
 * CheckoutFrame — the reserved-layout frame of the hosted checkout card.
 *
 * The skeleton AND every live state render THIS same frame with different
 * slot content, so the layout never shifts when data lands (zero-CLS by
 * construction). Slot minimum heights match the tallest typical content:
 * the action slot reserves a full button (>=44px touch target) and the
 * notice slot one line of copy.
 */

import type { ReactNode } from 'react'
import { Card, Shell } from '@/app/pay/_components/payUi'

export interface CheckoutFrameProps {
  header: ReactNode
  amount: ReactNode
  summary: ReactNode
  action: ReactNode
  notice: ReactNode
  footer: ReactNode
}

export function CheckoutFrame({
  header,
  amount,
  summary,
  action,
  notice,
  footer,
}: CheckoutFrameProps) {
  return (
    <Shell>
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div data-testid="frame-header" style={{ minHeight: 38 }}>
            {header}
          </div>
          <div data-testid="frame-amount" style={{ minHeight: 44 }}>
            {amount}
          </div>
          <div data-testid="frame-summary" style={{ minHeight: 118 }}>
            {summary}
          </div>
          <div
            data-testid="frame-action"
            style={{
              minHeight: 48,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              justifyContent: 'center',
            }}
          >
            {action}
          </div>
          <div
            data-testid="frame-notice"
            aria-live="polite"
            style={{ minHeight: 18 }}
          >
            {notice}
          </div>
          <div data-testid="frame-footer" style={{ minHeight: 60 }}>
            {footer}
          </div>
        </div>
      </Card>
    </Shell>
  )
}
