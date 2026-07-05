/**
 * Smoke-render the /vision and /team pages in every locale against the real
 * message files. next-intl's server runtime and the GSAP motion wrappers are
 * mocked (no Next request context / ScrollTrigger in jsdom); the messages,
 * page structure, and links are real.
 */
import { render, screen } from '@testing-library/react'

jest.mock('next-intl/server', () => ({
  getTranslations: async ({ locale, namespace }: { locale: string; namespace: string }) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require(`@/messages/${locale}.json`)
    const ns = messages[namespace]
    const resolve = (key: string) =>
      key.split('.').reduce((node: any, part: string) => node?.[part], ns)
    const t = (key: string) => {
      const value = resolve(key)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key} in ${locale}`)
      }
      return value
    }
    t.raw = (key: string) => {
      const value = resolve(key)
      if (value === undefined) {
        throw new Error(`Missing raw message ${namespace}.${key} in ${locale}`)
      }
      return value
    }
    return t
  },
}))

jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

jest.mock('@/components/motion/ScrubReveal', () => ({
  __esModule: true,
  default: ({ children }: any) => <div>{children}</div>,
}))

jest.mock('@/components/motion/ScrubCascade', () => ({
  __esModule: true,
  default: ({ children, style }: any) => <div style={style}>{children}</div>,
}))

import VisionPage from '@/app/[locale]/vision/page'
import TeamPage from '@/app/[locale]/team/page'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const
const ROUTER_ADDRESS = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'
const CONTRACT_URL = `https://sepolia.basescan.org/address/${ROUTER_ADDRESS}`

const props = (locale: string) => ({ params: Promise.resolve({ locale }) })

describe.each(LOCALES)('/%s/vision', locale => {
  it('renders headline, cards, timeline and the cross-link to /team', async () => {
    const { container } = render(await VisionPage(props(locale)))
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const m = require(`@/messages/${locale}.json`).vision

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(m.title)
    for (const card of m.cards) {
      expect(screen.getByText(card.title)).toBeInTheDocument()
    }
    // Timeline years/NEXT are locale-invariant DM Mono figures
    for (const year of ['2025', '2026', 'NEXT']) {
      expect(screen.getByText(year)).toBeInTheDocument()
    }
    expect(container.querySelector('a[href="/team"]')).not.toBeNull()
  })
})

describe.each(LOCALES)('/%s/team', locale => {
  it('renders headline, profiles, philosophy and the cross-link to /vision', async () => {
    const { container } = render(await TeamPage(props(locale)))
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const m = require(`@/messages/${locale}.json`).team

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(m.title)
    // Role labels are locale-invariant DM Mono
    expect(screen.getByText('CO-FOUNDER · LEAD ENGINEER')).toBeInTheDocument()
    expect(screen.getByText('CO-FOUNDER · LEGAL & COMMERCIAL')).toBeInTheDocument()
    for (const num of ['01', '02', '03', '04']) {
      expect(screen.getByText(num)).toBeInTheDocument()
    }
    // BaseScan mentions link the contract page
    const contractLinks = container.querySelectorAll(`a[href="${CONTRACT_URL}"]`)
    expect(contractLinks.length).toBeGreaterThanOrEqual(1)
    for (const a of Array.from(contractLinks)) {
      expect(a).toHaveAttribute('target', '_blank')
      expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    }
    expect(container.querySelector('a[href="/vision"]')).not.toBeNull()
  })
})
