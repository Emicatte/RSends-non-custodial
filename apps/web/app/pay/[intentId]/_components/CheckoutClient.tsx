'use client'

/**
 * CheckoutClient — mounts the wallet stack for the hosted checkout.
 *
 * /pay is intentionally OUTSIDE the global Providers (app/providers.tsx
 * bypasses it), so the full wagmi + RainbowKit stack is mounted here,
 * ssr-disabled, with the brand light theme re-applied by a nested
 * RainbowKitProvider — the exact pattern of the /pay root page.
 */

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { QueryClient } from '@tanstack/react-query'
import { RainbowKitProvider } from '@rainbow-me/rainbowkit'
import { rsendsWalletTheme } from '@/app/pay/_components/walletTheme'
import HostedCheckout from './HostedCheckout'

const WalletStackFull = dynamic(() => import('@/app/providers-wallet-stack'), {
  ssr: false,
})

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 8_000, retry: 2 } },
  })
}

export default function CheckoutClient() {
  const [queryClient] = useState(makeQueryClient)
  return (
    <WalletStackFull
      autoOpenModal={false}
      reconnectOnMount={true}
      queryClient={queryClient}
    >
      <RainbowKitProvider
        theme={rsendsWalletTheme}
        modalSize="compact"
        appInfo={{ appName: 'RSends' }}
      >
        <HostedCheckout />
      </RainbowKitProvider>
    </WalletStackFull>
  )
}
