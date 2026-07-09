/**
 * Company info step (CompanyProfileForm) — server-side autosave + submit gating.
 *
 * Proves: (1) rapid edits collapse into exactly ONE debounced PATCH carrying
 * the changed field, (2) submit stays disabled until both declarations are
 * ticked AND the PEP question is answered, (3) successful submit POSTs the
 * submit endpoint and routes to the dashboard.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

jest.mock('next-intl', () => ({
  useLocale: () => 'en',
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
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

import { CompanyProfileForm } from '@/components/onboarding/CompanyProfileForm'

const EMPTY_PROFILE_404 = {
  ok: false,
  status: 404,
  json: async () => ({ detail: { code: 'not_found' } }),
}

const PROFILE = {
  legal_name: null,
  trading_name: null,
  country: null,
  registration_number: null,
  tax_or_vat_number: null,
  website: null,
  business_category: null,
  expected_monthly_volume: null,
  countries_served: null,
  primary_stablecoin: null,
  no_sanctioned_countries: null,
  no_prohibited_activities: null,
  has_pep: null,
  submitted_at: null,
}

function mockFetch() {
  const fn = jest.fn().mockImplementation((url: unknown, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/company-profile/submit')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ ...PROFILE, submitted_at: '2026-07-09T00:00:00Z' }),
      })
    }
    if (u.includes('/company-profile')) {
      if (!init || !init.method || init.method === 'GET') {
        return Promise.resolve(EMPTY_PROFILE_404)
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => PROFILE })
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

function patchCalls(fn: jest.Mock) {
  return fn.mock.calls.filter(
    ([u, init]) =>
      String(u).includes('/company-profile') &&
      (init as RequestInit | undefined)?.method === 'PATCH',
  )
}

beforeEach(() => {
  replaceMock.mockClear()
})

afterEach(() => {
  jest.useRealTimers()
})

describe('CompanyProfileForm autosave', () => {
  it('collapses rapid edits into one debounced PATCH', async () => {
    const fetchMock = mockFetch()
    render(<CompanyProfileForm />)
    await act(async () => {}) // initial draft load settles

    jest.useFakeTimers()
    const legalName = screen.getByLabelText(/legal name/i)
    fireEvent.change(legalName, { target: { value: 'R' } })
    fireEvent.change(legalName, { target: { value: 'RP' } })
    fireEvent.change(legalName, { target: { value: 'RPagos S.R.L.' } })

    expect(patchCalls(fetchMock)).toHaveLength(0) // debounce pending

    await act(async () => {
      jest.advanceTimersByTime(800)
    })
    await act(async () => {}) // let the PATCH promise settle

    const calls = patchCalls(fetchMock)
    expect(calls).toHaveLength(1)
    expect(JSON.parse(String((calls[0][1] as RequestInit).body))).toMatchObject({
      legal_name: 'RPagos S.R.L.',
    })
  })

  it('gates submit on the declarations and the PEP answer, then submits', async () => {
    const fetchMock = mockFetch()
    render(<CompanyProfileForm />)
    await act(async () => {})

    const submit = screen.getByRole('button', { name: /submit company profile/i })
    expect(submit).toBeDisabled()

    // Tick both declarations (checkboxes) — still disabled: PEP unanswered.
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    expect(submit).toBeDisabled()

    // Answer the PEP yes/no radio.
    fireEvent.click(screen.getByRole('radio', { name: /no/i }))
    expect(submit).toBeEnabled()

    fireEvent.click(submit)
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/app'))

    const submitCall = fetchMock.mock.calls.find(([u]) =>
      String(u).includes('/company-profile/submit'),
    )
    expect(submitCall).toBeTruthy()
    expect((submitCall![1] as RequestInit).method).toBe('POST')
  })
})
