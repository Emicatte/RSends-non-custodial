import type { Metadata } from 'next'
import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import { authOptions } from '@/lib/auth-options'
import AppNav from '@/components/app/AppNav'
import AppSidebar from '@/components/app/AppSidebar'
import AppBottomNav from '@/components/app/AppBottomNav'
import AppTopbar from '@/components/app/AppTopbar'
import { TransactionPersistence } from '@/components/TransactionPersistence'
import { ContactsPersistence } from '@/components/ContactsPersistence'
import { PostLoginMerge } from '@/components/auth/PostLoginMerge'
import { EmailVerifyBanner } from '@/components/auth/EmailVerifyBanner'

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
  return (
    <>
      <AppNav />
      <AppSidebar />
      <AppBottomNav />
      <div
        className="min-h-screen pt-[55px] md:pt-[63px] md:pl-[210px]"
        style={{ background: '#f7f6f3' }}
      >
        <AppTopbar />
        <EmailVerifyBanner />
        {children}
      </div>
      <TransactionPersistence />
      <ContactsPersistence />
      <PostLoginMerge />
    </>
  )
}
