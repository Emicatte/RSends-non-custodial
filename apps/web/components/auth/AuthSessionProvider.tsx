'use client'

import { SessionProvider } from 'next-auth/react'
import { TokenRefreshBridge } from '@/components/auth/TokenRefreshBridge'

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={10 * 60}>
      <TokenRefreshBridge />
      {children}
    </SessionProvider>
  )
}
