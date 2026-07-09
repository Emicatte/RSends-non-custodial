/**
 * OAuth/legacy consent interstitial (ConsentForm).
 *
 * Proves: (1) submit stays disabled until BOTH checkboxes are ticked,
 * (2) accepting POSTs /api/v1/user/consents with both flags true and a
 * Bearer token, (3) the form routes onward from the returned state — an
 * un-submitted org goes to the company step, (4) the label links both legal
 * documents. The next-intl mock throws on missing keys → also guards the
 * onboarding.* namespace in en.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    const t = (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
    t.rich = (key: string, values: Record<string, (chunk: string) => unknown>) => {
      const raw = t(key)
      const parts: unknown[] = []
      const tagRe = /<(\w+)>(.*?)<\/\1>/g
      let last = 0
      let m: RegExpExecArray | null
      while ((m = tagRe.exec(raw)) !== null) {
        parts.push(raw.slice(last, m.index))
        const renderTag = values[m[1]]
        parts.push(renderTag ? renderTag(m[2]) : m[2])
        last = m.index + m[0].length
      }
      parts.push(raw.slice(last))
      return parts
    }
    return t
  },
}))

const replaceMock = jest.fn()
jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ replace: replaceMock, push: jest.fn() }),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok' },
    status: 'authenticated',
  }),
}))

import { ConsentForm } from '@/components/onboarding/ConsentForm'

const POST_CONSENT_STATE = {
  consents_current: true,
  age_attested: true,
  email_verified: true,
  active_org_id: 'o1',
  onboarding_status: 'email_verified',
  activation_status: 'not_started',
  company_profile: { exists: false, submitted_at: null },
}

function mockFetch() {
  const fn = jest.fn().mockImplementation((url: unknown) => {
    const u = String(url)
    if (u.includes('/api/v1/user/consents')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => POST_CONSENT_STATE,
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

beforeEach(() => {
  replaceMock.mockClear()
})

describe('ConsentForm', () => {
  it('keeps submit disabled until both checkboxes are ticked', () => {
    mockFetch()
    render(<ConsentForm />)

    const submit = screen.getByRole('button')
    expect(submit).toBeDisabled()

    const boxes = screen.getAllByRole('checkbox')
    expect(boxes).toHaveLength(2)

    fireEvent.click(boxes[0])
    expect(submit).toBeDisabled()

    fireEvent.click(boxes[1])
    expect(submit).toBeEnabled()

    fireEvent.click(boxes[0]) // untick → disabled again
    expect(submit).toBeDisabled()
  })

  it('records both consents with a Bearer token and routes to the company step', async () => {
    const fetchMock = mockFetch()
    render(<ConsentForm />)

    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    fireEvent.click(screen.getByRole('button'))

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/onboarding/company'))

    const call = fetchMock.mock.calls.find(([u]) =>
      String(u).includes('/api/v1/user/consents'),
    )
    expect(call).toBeTruthy()
    const [, init] = call as [unknown, RequestInit]
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      accept_documents: true,
      age_attested: true,
    })
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer tok')
  })

  it('links both legal documents', () => {
    mockFetch()
    render(<ConsentForm />)

    const links = screen.getAllByRole('link')
    const hrefs = links.map((l) => l.getAttribute('href'))
    expect(hrefs.some((h) => h?.includes('/docs/terms'))).toBe(true)
    expect(hrefs.some((h) => h?.includes('/docs/privacy'))).toBe(true)
  })
})
