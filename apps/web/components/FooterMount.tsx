'use client'

import dynamic from 'next/dynamic'
import { usePathname } from '@/i18n/navigation'

const FooterGlobe = dynamic(() => import('./FooterGlobe'), { ssr: false })

export default function FooterMount() {
  const pathname = usePathname()
  if (pathname.startsWith('/merchant') || pathname === '/app' || pathname.startsWith('/app/')) return null
  return <FooterGlobe />
}
