/**
 * @jest-environment node
 *
 * enforceOnboarding — denial vs unreachable.
 *
 * A timeout is not a denial. The guard must keep the fail-closed redirect for
 * explicit auth/onboarding states (401/403/other 4xx, missing token) but must
 * NOT bounce the user when the backend simply could not answer (network
 * error, timeout, 5xx — e.g. the Render free-tier cold start): those resolve
 * 'unreachable' so the layout can render the retry gate instead.
 */
import { redirect } from 'next/navigation'
import type { Session } from 'next-auth'
import { enforceOnboarding } from '@/lib/onboarding-guard'
import type { OnboardingState } from '@/lib/onboarding'

jest.mock('next/navigation', () => ({
  redirect: jest.fn((url: string) => {
    // Mimic next's real redirect(): throws an error carrying a digest.
    const err = new Error('NEXT_REDIRECT') as Error & { digest: string }
    err.digest = `NEXT_REDIRECT;replace;${url};307;`
    throw err
  }),
}))

const redirectMock = redirect as unknown as jest.Mock

const SESSION = { access_token: 'tok-123' } as unknown as Session

const ONBOARDED: OnboardingState = {
  consents_current: true,
  age_attested: true,
  email_verified: true,
  active_org_id: 'org_1',
  onboarding_status: 'company_submitted',
  activation_status: 'active',
  company_profile: { exists: true, submitted_at: '2026-01-01T00:00:00Z' },
}

function mockFetch(impl: () => Promise<Partial<Response>>) {
  const fn = jest.fn(impl as never)
  ;(global as unknown as { fetch: jest.Mock }).fetch = fn
  return fn
}

beforeAll(() => {
  process.env.RPAGOS_BACKEND_URL = 'http://backend.test'
})

beforeEach(() => {
  jest.clearAllMocks()
})

async function expectRedirect(promise: Promise<unknown>, target: string) {
  await expect(promise).rejects.toMatchObject({
    digest: expect.stringContaining('NEXT_REDIRECT'),
  })
  expect(redirectMock).toHaveBeenCalledWith(target)
}

it("returns 'ok' with no redirect when fully onboarded", async () => {
  mockFetch(async () => ({ ok: true, status: 200, json: async () => ONBOARDED }))

  await expect(enforceOnboarding(SESSION, 'en')).resolves.toBe('ok')
  expect(redirectMock).not.toHaveBeenCalled()
})

it('redirects to the consent step on 200 with stale consents (unchanged)', async () => {
  mockFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ...ONBOARDED, consents_current: false }),
  }))

  await expectRedirect(enforceOnboarding(SESSION, 'en'), '/en/onboarding/consent')
})

it('401 keeps the fail-closed redirect to the gate (unchanged)', async () => {
  mockFetch(async () => ({ ok: false, status: 401 }))
  await expectRedirect(enforceOnboarding(SESSION, 'en'), '/en/onboarding')
})

it('403 keeps the fail-closed redirect to the gate (unchanged)', async () => {
  mockFetch(async () => ({ ok: false, status: 403 }))
  await expectRedirect(enforceOnboarding(SESSION, 'en'), '/en/onboarding')
})

it('other 4xx (422) keeps the fail-closed redirect to the gate (unchanged)', async () => {
  mockFetch(async () => ({ ok: false, status: 422 }))
  await expectRedirect(enforceOnboarding(SESSION, 'en'), '/en/onboarding')
})

it("500 resolves 'unreachable' and does NOT redirect", async () => {
  mockFetch(async () => ({ ok: false, status: 500 }))

  await expect(enforceOnboarding(SESSION, 'en')).resolves.toBe('unreachable')
  expect(redirectMock).not.toHaveBeenCalled()
})

it("503 resolves 'unreachable' and does NOT redirect", async () => {
  mockFetch(async () => ({ ok: false, status: 503 }))

  await expect(enforceOnboarding(SESSION, 'en')).resolves.toBe('unreachable')
  expect(redirectMock).not.toHaveBeenCalled()
})

it("network error (TypeError) resolves 'unreachable' and does NOT redirect", async () => {
  mockFetch(async () => {
    throw new TypeError('fetch failed')
  })

  await expect(enforceOnboarding(SESSION, 'en')).resolves.toBe('unreachable')
  expect(redirectMock).not.toHaveBeenCalled()
})

it("timeout (TimeoutError from AbortSignal.timeout) resolves 'unreachable'", async () => {
  mockFetch(async () => {
    throw Object.assign(new Error('The operation timed out'), {
      name: 'TimeoutError',
    })
  })

  await expect(enforceOnboarding(SESSION, 'en')).resolves.toBe('unreachable')
  expect(redirectMock).not.toHaveBeenCalled()
})

it('missing access token redirects to the gate before any fetch (unchanged)', async () => {
  const fetchMock = mockFetch(async () => ({ ok: true, status: 200 }))

  await expectRedirect(
    enforceOnboarding({} as unknown as Session, 'en'),
    '/en/onboarding',
  )
  expect(fetchMock).not.toHaveBeenCalled()
})

it('sends no-store and a timeout signal with the fetch', async () => {
  const fetchMock = mockFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ONBOARDED,
  }))

  await enforceOnboarding(SESSION, 'en')

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  expect(url).toBe('http://backend.test/api/v1/user/onboarding')
  expect(init.cache).toBe('no-store')
  expect(init.signal).toBeDefined()
  expect(init.headers).toMatchObject({ Authorization: 'Bearer tok-123' })
})
