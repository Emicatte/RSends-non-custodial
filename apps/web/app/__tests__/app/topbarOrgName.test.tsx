/**
 * AppTopbar — the org badge must be the ACTIVE ORG'S real name (from the
 * session /organizations fetch), not the custodial-era hardcoded "RPagos SRL"
 * mock string.
 */
import { render, screen, waitFor } from '@testing-library/react'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      ? namespace
          .split('.')
          .reduce((node: any, part: string) => node?.[part], messages)
      : messages
    return (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  usePathname: () => '/app',
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok' },
    status: 'authenticated',
  }),
}))

import AppTopbar from '@/components/app/AppTopbar'

const ORG_PAYLOAD = {
  organizations: [
    {
      id: 'o1',
      name: 'Acme Workspace',
      slug: 'acme',
      owner_user_id: 'u1',
      is_personal: false,
      plan: 'free',
      settlement_wallet: null,
      role: 'admin',
      member_count: 1,
      created_at: '2026-07-01T00:00:00Z',
    },
  ],
  active_org_id: 'o1',
}

beforeEach(() => {
  global.fetch = jest.fn().mockImplementation(() =>
    Promise.resolve({ ok: true, status: 200, json: async () => ORG_PAYLOAD })
  ) as unknown as typeof fetch
})

test('renders the active org name, never the hardcoded mock', async () => {
  render(<AppTopbar />)
  await waitFor(() =>
    expect(screen.getByText('Acme Workspace')).toBeInTheDocument()
  )
  expect(screen.queryByText(/RPagos/)).toBeNull()
})
