import type { Metadata } from 'next'
import { DocsLayout } from './_components/DocsLayout'

export const metadata: Metadata = {
  title: {
    default: 'RSends Docs — Non-custodial stablecoin payments',
    template: '%s — RSends Docs',
  },
  description:
    'Accept stablecoin payments without holding funds or keys. REST API reference and integration guide for the RSends non-custodial payment gateway — payments settle directly to your wallet on-chain.',
}

export default function DocsRootLayout({ children }: { children: React.ReactNode }) {
  return <DocsLayout>{children}</DocsLayout>
}
