import type { Metadata } from 'next'
import AppNav from '@/components/app/AppNav'
import AppSidebar from '@/components/app/AppSidebar'
import { TransactionPersistence } from '@/components/TransactionPersistence'
import { ContactsPersistence } from '@/components/ContactsPersistence'
import { PostLoginMerge } from '@/components/auth/PostLoginMerge'

export const metadata: Metadata = {
  title: 'RSends — App',
  description: 'Send, swap and manage crypto payments.',
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppNav />
      <AppSidebar />
      <div
        className="min-h-screen pt-[75px] md:pt-[90px] md:pl-[210px]"
        style={{ background: '#f7f6f3' }}
      >
        {children}
      </div>
      <TransactionPersistence />
      <ContactsPersistence />
      <PostLoginMerge />
    </>
  )
}
