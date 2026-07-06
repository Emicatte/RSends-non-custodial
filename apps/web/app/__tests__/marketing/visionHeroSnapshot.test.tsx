/**
 * Extraction guard: the /vision hero markup was recorded BEFORE the hero was
 * extracted into the shared MediaHero component. If this snapshot ever needs
 * an update, the extraction (or a later change) altered /vision's rendered
 * hero — that must be a deliberate design decision, never refactoring fallout.
 * Run with --ci so drift fails instead of silently rewriting the snapshot.
 */
import { render } from '@testing-library/react'

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

const props = (locale: string) => ({ params: Promise.resolve({ locale }) })

it('vision hero markup is stable across the MediaHero extraction', async () => {
  const { container } = render(await VisionPage(props('en')))
  const hero = container.querySelector('main > section')
  expect(hero).not.toBeNull()
  expect(hero!.outerHTML).toMatchSnapshot()
})
