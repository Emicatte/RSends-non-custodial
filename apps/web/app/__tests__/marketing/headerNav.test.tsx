/**
 * The marketing header must render the flat nav (How it works · Pricing ·
 * Vision · Team) with per-locale labels — in the desktop row AND the mobile
 * disclosure panel — and mount only on the marketing routes, never on the
 * app/dashboard shell.
 */
import { fireEvent, render, screen } from '@testing-library/react'

let currentLocale = 'en'
let currentPathname = '/'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require(`@/messages/${currentLocale}.json`)
    return (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], messages[namespace])
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

jest.mock('@/components/LanguageSwitcher', () => ({
  __esModule: true,
  default: () => <div data-testid="language-switcher" />,
}))

jest.mock('@/components/auth/LandingAuthButtons', () => ({
  LandingAuthButtons: () => <div data-testid="auth-buttons" />,
}))

import MarketingNav from '@/components/marketing/MarketingNav'
import HeaderMount from '@/components/marketing/HeaderMount'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const

describe.each(LOCALES)('MarketingNav (%s)', locale => {
  beforeEach(() => {
    currentLocale = locale
    currentPathname = '/'
  })

  it('renders localized links to how-it-works, pricing, vision and team', () => {
    render(<MarketingNav />)
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const nav = require(`@/messages/${locale}.json`).nav

    for (const [key, href] of [
      ['howItWorks', '/how-it-works'],
      ['pricing', '/pricing'],
      ['vision', '/vision'],
      ['team', '/team'],
    ] as const) {
      const link = screen.getByText(nav[key]).closest('a')
      expect(link).not.toBeNull()
      expect(link).toHaveAttribute('href', href)
    }
  })

  it('includes all four links, team included, in the mobile disclosure panel', () => {
    const { container } = render(<MarketingNav />)
    fireEvent.click(screen.getByLabelText('Menu'))

    const panel = container.querySelector('#rs-mnav-panel')
    expect(panel).not.toBeNull()
    for (const href of ['/how-it-works', '/pricing', '/vision', '/team']) {
      expect(panel!.querySelector(`a[href="${href}"]`)).not.toBeNull()
    }
  })

  it('links the logo to the home page and keeps the right-side controls', () => {
    const { container } = render(<MarketingNav />)
    expect(container.querySelector('a[href="/"]')).not.toBeNull()
    expect(screen.getByTestId('language-switcher')).toBeInTheDocument()
    expect(screen.getByTestId('auth-buttons')).toBeInTheDocument()
  })
})

describe('HeaderMount', () => {
  beforeEach(() => {
    currentLocale = 'en'
  })

  it.each(['/', '/pricing', '/how-it-works', '/vision', '/team'])(
    'mounts the nav on marketing route %s',
    pathname => {
      currentPathname = pathname
      const { container } = render(<HeaderMount />)
      expect(container.querySelector('nav')).not.toBeNull()
    },
  )

  it.each(['/settings', '/app', '/app/transactions', '/markets', '/merchant/dashboard', '/login'])(
    'does not mount the nav on app route %s',
    pathname => {
      currentPathname = pathname
      const { container } = render(<HeaderMount />)
      expect(container.querySelector('nav')).toBeNull()
    },
  )
})
