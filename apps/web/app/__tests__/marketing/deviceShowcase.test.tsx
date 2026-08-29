/**
 * The landing page's device showcase section shows the two real surfaces —
 * the merchant dashboard in a laptop frame, the payer's /pay page in a phone
 * frame. These assertions pin the three things that can silently rot:
 *
 *  - the images are real, described, and dimensioned (no unsized lazy load,
 *    which is how a section like this earns a CLS regression);
 *  - the copy resolves in all five locales, not just English, which is what
 *    the previous attempt at this section shipped;
 *  - the screenshots never show a balance. RSends is non-custodial and holds
 *    no funds, so a "Saldo totale" / "Total balance" figure in the shop
 *    window would contradict the product's central claim.
 */
import { render } from '@testing-library/react'

let currentLocale = 'en'

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

import DeviceShowcase from '@/components/landing/DeviceShowcase'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const

/** The label that names the screenshots as demo data, per locale. */
function demoDataLabel(locale: string): string {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const showcase = require(`@/messages/${locale}.json`).showcase
  if (!showcase || typeof showcase.demoDataLabel !== 'string') {
    throw new Error(`Missing message showcase.demoDataLabel in ${locale}`)
  }
  return showcase.demoDataLabel
}

/**
 * True when some ancestor reserves the box before the bytes arrive. Only
 * INLINE styles are readable in jsdom — a stylesheet rule is invisible here —
 * so the component must declare the reservation inline for this to hold.
 */
function hasReservedAncestor(img: HTMLImageElement): boolean {
  let node: HTMLElement | null = img.parentElement
  while (node) {
    const { aspectRatio, height } = node.style
    if (aspectRatio && aspectRatio !== 'auto') return true
    if (height && height !== 'auto' && height !== '') return true
    node = node.parentElement
  }
  return false
}

describe('DeviceShowcase', () => {
  beforeEach(() => {
    currentLocale = 'en'
  })

  it('renders both device screenshots', () => {
    const { container } = render(<DeviceShowcase />)
    expect(container.querySelectorAll('img')).toHaveLength(2)
  })

  it('describes each screenshot with its own non-empty alt text', () => {
    const { container } = render(<DeviceShowcase />)
    const alts = Array.from(container.querySelectorAll('img')).map(img => img.getAttribute('alt'))
    expect(alts).toHaveLength(2)

    for (const alt of alts) {
      expect(alt).toBeTruthy()
      expect((alt as string).trim().length).toBeGreaterThan(0)
    }
    expect(new Set(alts).size).toBe(alts.length)
  })

  it('gives every screenshot an explicit numeric width and height', () => {
    const { container } = render(<DeviceShowcase />)
    const imgs = Array.from(container.querySelectorAll('img'))
    // Guard the loop: an empty NodeList would satisfy every assertion below.
    expect(imgs).toHaveLength(2)

    for (const img of imgs) {
      const width = img.getAttribute('width')
      const height = img.getAttribute('height')
      expect(width).toMatch(/^\d+$/)
      expect(height).toMatch(/^\d+$/)
    }
  })

  it('labels the screenshots as demo data', () => {
    const { container } = render(<DeviceShowcase />)
    expect(container.textContent).toContain(demoDataLabel('en'))
  })

  it('never lazy loads a screenshot into an unsized container', () => {
    const { container } = render(<DeviceShowcase />)
    const imgs = Array.from(container.querySelectorAll('img'))
    // Guard: with no images at all the filter below is vacuously satisfied.
    expect(imgs).toHaveLength(2)
    const lazy = imgs.filter(img => img.getAttribute('loading') === 'lazy')

    for (const img of lazy) {
      expect(hasReservedAncestor(img as HTMLImageElement)).toBe(true)
    }
  })

  describe.each(LOCALES)('in %s', locale => {
    beforeEach(() => {
      currentLocale = locale
    })

    it('resolves every message key it uses', () => {
      expect(() => render(<DeviceShowcase />)).not.toThrow()
    })

    it('shows no balance figure', () => {
      const { container } = render(<DeviceShowcase />)
      expect(container.textContent).not.toMatch(/saldo\s+totale/i)
      expect(container.textContent).not.toMatch(/total\s+balance/i)
    })
  })
})
