/**
 * Blocking logout (audit finding #7).
 *
 * The old flow was fire-and-forget: `void signOut(); void fetch(logout)`.
 * If the backend call failed, the Redis session stayed alive (up to 7 days)
 * and the HttpOnly refresh/sid cookies remained — JS can't clear them — so a
 * shared device could silently mint new access tokens via /auth/refresh.
 *
 * performLogout pins the fixed contract:
 *  - the backend logout is AWAITED (bounded retry) and client sign-out is
 *    GATED on it succeeding — never a silent half-logout;
 *  - on persistent backend failure it returns ok:false WITHOUT signing out,
 *    so the UI keeps the session visible and surfaces the error;
 *  - skipBackend covers the expired-session path (failed refresh): the server
 *    session is already dead there, requiring a logout call would deadlock.
 */
import { performLogout } from '@/lib/logoutClient'
import { signOut } from 'next-auth/react'

jest.mock('next-auth/react', () => ({
  signOut: jest.fn(async () => undefined),
}))

const signOutMock = signOut as unknown as jest.Mock

function mockFetchSequence(...impls: Array<() => Promise<Partial<Response>>>) {
  const fn = jest.fn()
  for (const impl of impls) fn.mockImplementationOnce(impl as never)
  ;(global as unknown as { fetch: jest.Mock }).fetch = fn
  return fn
}

beforeEach(() => {
  jest.clearAllMocks()
})

it('signs out only after the backend logout succeeds', async () => {
  const fetchMock = mockFetchSequence(async () => ({ ok: true, status: 200 }))

  const result = await performLogout()

  expect(result.ok).toBe(true)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock.mock.calls[0][0]).toBe('/api/rp-auth/api/v1/auth/logout')
  expect(fetchMock.mock.calls[0][1]).toMatchObject({
    method: 'POST',
    credentials: 'include',
  })
  expect(signOutMock).toHaveBeenCalledTimes(1)
})

it('does NOT sign out when the backend logout keeps failing', async () => {
  const fetchMock = mockFetchSequence(
    async () => ({ ok: false, status: 503 }),
    async () => {
      throw new Error('network down')
    },
  )

  const result = await performLogout()

  expect(result.ok).toBe(false)
  expect(fetchMock).toHaveBeenCalledTimes(2) // bounded retry, then give up
  expect(signOutMock).not.toHaveBeenCalled() // no silent half-logout
})

it('retries once and signs out when the retry succeeds', async () => {
  const fetchMock = mockFetchSequence(
    async () => {
      throw new Error('blip')
    },
    async () => ({ ok: true, status: 200 }),
  )

  const result = await performLogout()

  expect(result.ok).toBe(true)
  expect(fetchMock).toHaveBeenCalledTimes(2)
  expect(signOutMock).toHaveBeenCalledTimes(1)
})

it('skipBackend signs out without calling the backend (expired-session path)', async () => {
  const fetchMock = mockFetchSequence()

  const result = await performLogout({ skipBackend: true })

  expect(result.ok).toBe(true)
  expect(fetchMock).not.toHaveBeenCalled()
  expect(signOutMock).toHaveBeenCalledTimes(1)
})

it('forwards callbackUrl to signOut on success', async () => {
  mockFetchSequence(async () => ({ ok: true, status: 200 }))

  await performLogout({ callbackUrl: '/en' })

  expect(signOutMock).toHaveBeenCalledWith({ callbackUrl: '/en' })
})

// ── PII clearing on sign-out (audit finding #8) ──────────────
// On a shared device a logged-out user's address book / fiscal records must
// not stay readable. Clearing consciously trades away cross-logout
// offline-first persistence.

const PII_KEYS = [
  'rp_address_book',
  'rsends.pendingMerge',
  'rsend_antiphishing_code',
  'rp_pending_queue',
  'rp_compliance_db',
]

function seedStorage() {
  for (const key of PII_KEYS) localStorage.setItem(key, '[{"pii":true}]')
  localStorage.setItem('rs_cg_prices', '{"eth":1}') // non-PII cache — must survive
}

it('clears user PII from localStorage after a successful logout', async () => {
  mockFetchSequence(async () => ({ ok: true, status: 200 }))
  seedStorage()

  const result = await performLogout()

  expect(result.ok).toBe(true)
  for (const key of PII_KEYS) expect(localStorage.getItem(key)).toBeNull()
  expect(localStorage.getItem('rs_cg_prices')).toBe('{"eth":1}')
})

it('clears user PII on the skipBackend (expired-session) path too', async () => {
  mockFetchSequence()
  seedStorage()

  await performLogout({ skipBackend: true })

  for (const key of PII_KEYS) expect(localStorage.getItem(key)).toBeNull()
})

it('does NOT clear PII when the backend logout fails (user is still signed in)', async () => {
  mockFetchSequence(
    async () => ({ ok: false, status: 503 }),
    async () => ({ ok: false, status: 503 }),
  )
  seedStorage()

  const result = await performLogout()

  expect(result.ok).toBe(false)
  for (const key of PII_KEYS) expect(localStorage.getItem(key)).not.toBeNull()
})
