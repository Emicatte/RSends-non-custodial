/**
 * The footer legal line must credit the actual legal entity, RPagos S.R.L. —
 * never the fictitious "RSends Inc.".
 */
import { render, screen } from '@testing-library/react'

// FooterGlobe imports the locale-aware Link; next-intl ships untranspiled ESM
// that Jest can't parse, and navigation is irrelevant here.
jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

import FooterGlobe from '@/components/FooterGlobe'

describe('footer legal entity', () => {
  it('credits RPagos S.R.L. and not RSends Inc.', () => {
    render(<FooterGlobe />)
    expect(screen.getByText('RPagos S.R.L.')).toBeInTheDocument()
    expect(screen.queryByText(/RSends Inc\./)).toBeNull()
  })
})
