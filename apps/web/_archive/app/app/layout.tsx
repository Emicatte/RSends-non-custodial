// @ts-nocheck — archived reference code, excluded from the build (tsconfig "exclude");
// kept only for future reuse. The IDE type-checks open files regardless of the exclude.
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'RSends — App',
  description: 'Send, swap and manage crypto payments.',
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
