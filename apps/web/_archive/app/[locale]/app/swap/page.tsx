'use client'

import SwapModule from '@/app/SwapModule'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'

export default function SwapPage() {
  return (
    <main style={{ padding: '24px 20px 80px', maxWidth: 680, margin: '0 auto' }}>
      <ErrorBoundary module="SwapModule">
        <SwapModule noCard onSwapComplete={() => {}} />
      </ErrorBoundary>
    </main>
  )
}
