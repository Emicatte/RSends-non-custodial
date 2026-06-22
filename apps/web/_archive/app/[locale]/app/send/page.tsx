'use client'

import TransferForm from '@/app/TransferForm'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'

export default function SendPage() {
  return (
    <main style={{ padding: '24px 20px 80px', maxWidth: 680, margin: '0 auto' }}>
      <ErrorBoundary module="TransferForm">
        <TransferForm noCard />
      </ErrorBoundary>
    </main>
  )
}
