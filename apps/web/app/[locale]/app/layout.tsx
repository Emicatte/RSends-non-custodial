import type { Metadata } from 'next'
import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import { authOptions } from '@/lib/auth-options'
import { enforceOnboarding } from '@/lib/onboarding-guard'
import { BackendUnreachableGate } from '@/components/app/BackendUnreachableGate'
import AppNav from '@/components/app/AppNav'
import AppSidebar from '@/components/app/AppSidebar'
import AppBottomNav from '@/components/app/AppBottomNav'
import AppTopbar from '@/components/app/AppTopbar'
import { TransactionPersistence } from '@/components/TransactionPersistence'
import { ContactsPersistence } from '@/components/ContactsPersistence'
import { PostLoginMerge } from '@/components/auth/PostLoginMerge'
import { TestnetBanner } from '@/components/app/TestnetBanner'

export const metadata: Metadata = {
  title: 'RSends — App',
  description: 'Send, swap and manage crypto payments.',
}

export default async function AppLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  const session = await getServerSession(authOptions)
  if (!session) {
    redirect(`/${locale}/login`)
  }
  // Staged onboarding, enforced server-side: sessions without current
  // consents/age attestation or an un-submitted company profile never render
  // the dashboard (fail-closed to the /onboarding gate page). An unreachable
  // backend is NOT a denial: render the client retry gate instead of bouncing.
  // A stale (expired) access token gets the same gate — it refreshes the
  // token in place and re-runs this guard, keeping the user on their URL.
  const guard = await enforceOnboarding(session, locale)
  if (guard === 'unreachable' || guard === 'stale-token') {
    return <BackendUnreachableGate />
  }
  return (
    <>
      <AppNav />
      <AppSidebar />
      <AppBottomNav />
      <div
        className="min-h-screen pt-14 md:pt-16 md:pl-52"
        style={{ background: '#f7f6f3' }}
      >
        <AppTopbar />
        <TestnetBanner />
        {children}
      </div>
      <TransactionPersistence />
      <ContactsPersistence />
      <PostLoginMerge />
    </>
  )
}
