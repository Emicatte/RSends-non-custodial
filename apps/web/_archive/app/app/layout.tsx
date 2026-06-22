import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'RSends — App',
  description: 'Send, swap and manage crypto payments.',
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
