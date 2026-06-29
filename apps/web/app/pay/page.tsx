'use client'

/**
 * app/pay/page.tsx — params-driven non-custodial checkout (= /pay).
 *
 *   /pay?token=USDC&amount=100&to=0x…&ref=INV-001  → on-chain checkout
 *   /pay                                            → merchant request generator
 *
 * This route is intentionally OUTSIDE the global wallet Providers and the
 * next-intl middleware (both bypass /pay), so we mount the full wallet stack
 * (wagmi + RainbowKit) ourselves — reusing the exact pattern from
 * app/pay/[intentId]/page.tsx. It is additive and does not touch that page.
 */
import { Suspense, useState } from 'react'
import dynamic from 'next/dynamic'
import { useSearchParams } from 'next/navigation'
import { QueryClient } from '@tanstack/react-query'
import { RainbowKitProvider } from '@rainbow-me/rainbowkit'
import { C } from '@/app/designTokens'
import { parsePayParams } from '@/lib/web3/payParams'
import { Shell, Card, TestnetBadge, Spinner, Eyebrow, GhostButton } from './_components/payUi'
import { rsendsWalletTheme } from './_components/walletTheme'
import CheckoutPanel from './_components/CheckoutPanel'
import RequestGenerator from './_components/RequestGenerator'

const WalletStackFull = dynamic(() => import('@/app/providers-wallet-stack'), { ssr: false })

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { staleTime: 8_000, retry: 2 } } })
}

export default function PayPage() {
  const [queryClient] = useState(makeQueryClient)
  return (
    <WalletStackFull autoOpenModal={false} reconnectOnMount={true} queryClient={queryClient}>
      {/* Nested provider re-themes the Connect button + modal to brand (light +
          terracotta) for the /pay subtree only. wagmi/connectors come from the
          outer WalletStackFull — not re-instantiated. */}
      <RainbowKitProvider theme={rsendsWalletTheme} modalSize="compact" appInfo={{ appName: 'RSends' }}>
        <Shell>
          <Suspense fallback={<LoadingCard />}>
            <PayContent />
          </Suspense>
          <TestnetBadge />
        </Shell>
      </RainbowKitProvider>
    </WalletStackFull>
  )
}

function PayContent() {
  const sp = useSearchParams()
  const token = sp.get('token')
  const amount = sp.get('amount')
  const to = sp.get('to')
  const ref = sp.get('ref')

  // No payment params → merchant generator.
  if (!token && !amount && !to) return <RequestGenerator />

  const parsed = parsePayParams({ token, amount, to, ref })
  if (!parsed.ok) return <InvalidRequest message={parsed.error} />
  return <CheckoutPanel request={parsed.request} />
}

function LoadingCard() {
  return (
    <Card>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '28px 0' }}>
        <Spinner size={24} />
        <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.sub }}>Loading checkout…</p>
      </div>
    </Card>
  )
}

function InvalidRequest({ message }: { message: string }) {
  return (
    <Card>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Eyebrow>Payment request</Eyebrow>
        <h1 style={{ margin: 0, fontFamily: C.D, fontSize: 22, fontWeight: 600, color: C.text }}>
          This link isn’t valid
        </h1>
        <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.sub, lineHeight: 1.5 }}>
          {message}
        </p>
        <a href="/pay" style={{ textDecoration: 'none' }}>
          <GhostButton>Create a new payment link</GhostButton>
        </a>
      </div>
    </Card>
  )
}
