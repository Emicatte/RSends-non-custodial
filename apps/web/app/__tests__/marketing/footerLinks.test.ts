/**
 * The site footer must link to both marketing pages, /vision and /team,
 * from the Company column.
 */

// FooterGlobe imports the locale-aware Link; next-intl ships untranspiled ESM
// that Jest can't parse, and the navigation module is irrelevant to this test.
jest.mock('@/i18n/navigation', () => ({ Link: () => null }))

import { COLUMNS } from '@/components/FooterGlobe'

describe('footer links', () => {
  const allLinks = COLUMNS.flatMap(col => col.links)

  it('contains a link to /vision', () => {
    expect(allLinks.map(l => l.href)).toContain('/vision')
  })

  it('contains a link to /team', () => {
    expect(allLinks.map(l => l.href)).toContain('/team')
  })

  it('puts both in the Company column', () => {
    const company = COLUMNS.find(col => col.title === 'Company')
    expect(company).toBeDefined()
    const hrefs = company!.links.map(l => l.href)
    expect(hrefs).toEqual(expect.arrayContaining(['/vision', '/team']))
  })
})
