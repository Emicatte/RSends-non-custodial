'use client'

import { Link, usePathname } from '@/i18n/navigation'
import {
  AppSidebarView,
  SIDEBAR_SECTIONS,
  type SidebarKey,
  type SidebarLinkProps,
} from './AppSidebarView'

/**
 * The dashboard's left rail: `AppSidebarView` wired to the router.
 *
 * Everything visual lives in the view. This file holds the two things that are
 * genuinely about being inside `/app` — which entry the current pathname makes
 * active, and that the entries are real next-intl links. The landing page's
 * device mockup renders the view directly, with neither.
 */

function isActive(pathname: string, href: string): boolean {
  if (href === '/app') return pathname === '/app'
  return pathname === href || pathname.startsWith(href + '/')
}

const routerLink = ({ href, className, style, children }: SidebarLinkProps) => (
  <Link href={href} className={className} style={style}>
    {children}
  </Link>
)

export default function AppSidebar() {
  const pathname = usePathname()
  const activeKey =
    SIDEBAR_SECTIONS.flatMap((s) => s.items).find((i) => isActive(pathname, i.href))?.key ??
    null

  return (
    <AppSidebarView
      activeKey={activeKey as SidebarKey | null}
      variant="fixed"
      renderLink={routerLink}
    />
  )
}
