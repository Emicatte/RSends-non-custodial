'use client'

// app/docs/_components/DocsLayout.tsx
//
// Persistent shell for the RSends docs: brand wordmark, grouped left sidebar
// with a terracotta active item (driven by usePathname), the site-wide honesty
// status line, and the content column. English-only; lives outside next-intl
// (served at /docs/* with no locale prefix).

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import type { ReactNode } from 'react'
import { StatusLine } from './StatusLine'

type NavItem = { href: string; label: string }
type NavGroup = { title: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  {
    title: 'Get started',
    items: [
      { href: '/docs', label: 'Overview' },
      { href: '/docs/authentication', label: 'Authentication' },
      { href: '/docs/testing', label: 'Testing' },
    ],
  },
  {
    title: 'Payments',
    items: [
      { href: '/docs/payment-intents', label: 'Payment intents' },
      { href: '/docs/hosted-checkout', label: 'Hosted checkout' },
      { href: '/docs/webhooks', label: 'Webhooks' },
    ],
  },
  {
    title: 'After payment',
    items: [
      { href: '/docs/reporting', label: 'Reporting' },
      { href: '/docs/refunds', label: 'Refunds' },
      { href: '/docs/errors', label: 'Errors' },
    ],
  },
]

function isActive(pathname: string, href: string) {
  // Exact match — every docs page has its own route, /docs is the Overview.
  return pathname === href
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      className={`-ml-px block border-l-2 pl-4 font-display text-[13.5px] transition-colors ${
        active
          ? 'border-terracotta font-medium text-terracotta'
          : 'border-transparent text-ink/55 hover:text-ink'
      }`}
    >
      {item.label}
    </Link>
  )
}

export function DocsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/docs'

  return (
    <div className="min-h-[100dvh] bg-paper text-ink">
      <div className="mx-auto flex max-w-[1180px] gap-12 px-6 md:px-10">
        {/* ── Sidebar (desktop) ───────────────────────────────── */}
        <aside className="sticky top-0 hidden h-[100dvh] w-60 shrink-0 flex-col overflow-y-auto py-10 md:flex">
          <Link href="/docs" className="mb-10 inline-flex items-baseline gap-2">
            <span className="font-display text-[18px] font-semibold tracking-[-0.02em] text-ink">
              RSends
            </span>
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-terracotta">
              Docs
            </span>
          </Link>

          <nav aria-label="Documentation" className="space-y-7">
            {NAV.map((group) => (
              <div key={group.title}>
                <p className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.16em] text-ink/35">
                  {group.title}
                </p>
                <ul className="space-y-1.5 border-l border-ink/10">
                  {group.items.map((item) => (
                    <li key={item.href}>
                      <SidebarLink item={item} active={isActive(pathname, item.href)} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <a
            href="https://demo.rsends.io"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-auto pt-8 font-mono text-[11px] text-ink/40 transition-colors hover:text-terracotta"
          >
            demo.rsends.io ↗
          </a>
        </aside>

        {/* ── Content column ──────────────────────────────────── */}
        <div className="min-w-0 flex-1 pb-28 pt-10 md:pt-16">
          {/* Mobile nav strip */}
          <div className="mb-8 flex gap-2 overflow-x-auto pb-1 md:hidden">
            {NAV.flatMap((g) => g.items).map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive(pathname, item.href) ? 'page' : undefined}
                className={`shrink-0 rounded-full border px-3.5 py-1.5 font-display text-[12.5px] transition-colors ${
                  isActive(pathname, item.href)
                    ? 'border-terracotta bg-wash/50 font-medium text-terracotta'
                    : 'border-ink/12 text-ink/55'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </div>

          {/* Breadcrumb */}
          <nav aria-label="Breadcrumb" className="mb-6">
            <ol className="flex items-center gap-2 font-display text-[13px] text-ink/50">
              <li>
                <a href="https://pay.rsends.io" className="transition-colors hover:text-ink">
                  pay.rsends.io
                </a>
              </li>
              <li className="text-ink/25" aria-hidden>/</li>
              <li className="font-medium text-ink">Docs</li>
            </ol>
          </nav>

          <StatusLine />

          <article className="min-w-0">{children}</article>
        </div>
      </div>
    </div>
  )
}
