'use client'

import dynamic from 'next/dynamic'
import { useAccount, useChainId } from 'wagmi'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
import { C } from '@/app/designTokens'

const CommandCenter = dynamic(() => import('@/app/command-center'), {
  ssr: false,
  loading: () => (
    <div style={{ padding: 40, textAlign: 'center', color: C.sub, fontFamily: C.D }}>
      …
    </div>
  ),
})

export default function FlowPage() {
  const { address } = useAccount()
  const chainId = useChainId()
  return (
    <main style={{ padding: '24px 20px 80px', maxWidth: 680, margin: '0 auto' }}>
      <ErrorBoundary module="CommandCenter">
        <CommandCenter ownerAddress={address} chainId={chainId} isVisible={true} />
      </ErrorBoundary>
    </main>
  )
}
