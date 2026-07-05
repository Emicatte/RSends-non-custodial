'use client'

import { usePathname } from '@/i18n/navigation'
import MarketingNav from './MarketingNav'

// Allowlist, not denylist: the marketing header must never leak onto the
// app/dashboard shell (settings, markets, merchant, login…), which lives flat
// under the same [locale] segment. Mirrors the FooterMount pattern.
const MARKETING_PATHS = ['/pricing', '/how-it-works', '/vision', '/team']

export default function HeaderMount() {
  const pathname = usePathname()
  const isMarketing =
    pathname === '/' ||
    MARKETING_PATHS.some(p => pathname === p || pathname.startsWith(`${p}/`))
  if (!isMarketing) return null
  return <MarketingNav />
}
