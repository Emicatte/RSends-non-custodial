/**
 * Phase A regression guard: the non-custodial `/app` sidebar must NOT surface any
 * custodial or mock entry (send / swap / flow / command-center / transactions /
 * balances / clients / reports), and the Settings entry must point at the live
 * session-guarded `/settings` area — not the removed `/app/settings` mock.
 *
 * Rendered across all 5 locales; the next-intl mock throws on any missing message,
 * so this also proves the sidebar references no dangling i18n key.
 */
import { render } from '@testing-library/react'

let currentLocale = 'en'
let currentPathname = '/app'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require(`@/messages/${currentLocale}.json`)
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    return (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key} in ${currentLocale}`)
      }
      return value
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  usePathname: () => currentPathname,
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

import AppSidebar from '@/components/app/AppSidebar'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const

const REMOVED_HREFS = [
  '/app/send',
  '/app/swap',
  '/app/flow',
  '/app/command-center',
  '/app/transactions',
  '/app/balances',
  '/app/clients',
  '/app/reports',
  '/app/settings',
]

describe.each(LOCALES)('AppSidebar (%s)', locale => {
  beforeEach(() => {
    currentLocale = locale
    currentPathname = '/app'
  })

  it('renders no custodial or mock nav entries', () => {
    const { container } = render(<AppSidebar />)
    const hrefs = Array.from(container.querySelectorAll('a')).map(a =>
      a.getAttribute('href'),
    )
    for (const removed of REMOVED_HREFS) {
      expect(hrefs).not.toContain(removed)
    }
  })

  it('keeps Dashboard and points Settings at the live /settings area', () => {
    const { container } = render(<AppSidebar />)
    const hrefs = Array.from(container.querySelectorAll('a')).map(a =>
      a.getAttribute('href'),
    )
    expect(hrefs).toContain('/app')
    expect(hrefs).toContain('/settings')
  })
})
