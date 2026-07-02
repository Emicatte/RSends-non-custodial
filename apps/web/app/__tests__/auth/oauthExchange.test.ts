/**
 * OAuth token exchange (account-linking audit, layer 3).
 *
 * AuthBootstrap used to swallow EVERY non-OK response from the backend token
 * exchange — including the 409 email_already_registered collision guard — so
 * a user hitting the block-and-guide path saw nothing at all. The helper pins
 * the contract: 409 is a distinct 'conflict' outcome (surfaced to the
 * AccountLinkingModal by the caller), success carries the access token, and
 * only transport/other failures collapse to 'error'.
 */
import { exchangeOAuthToken } from '@/lib/oauthExchange'

function mockFetchOnce(impl: () => Promise<Partial<Response>>) {
  ;(global as unknown as { fetch: jest.Mock }).fetch = jest.fn(impl as never)
}

const ENDPOINT = '/api/rp-auth/api/v1/auth/google'
const BODY = { id_token: 'tok' }

it('returns ok + access token on 200', async () => {
  mockFetchOnce(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ access_token: 'jwt-123' }),
  }))

  const res = await exchangeOAuthToken(ENDPOINT, BODY)

  expect(res).toEqual({ status: 'ok', accessToken: 'jwt-123' })
  const fetchMock = (global as unknown as { fetch: jest.Mock }).fetch
  expect(fetchMock).toHaveBeenCalledWith(ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(BODY),
    credentials: 'include',
  })
})

it('surfaces the 409 collision as a distinct conflict (not swallowed)', async () => {
  mockFetchOnce(async () => ({
    ok: false,
    status: 409,
    json: async () => ({
      detail: { code: 'email_already_registered' },
    }),
  }))

  const res = await exchangeOAuthToken(ENDPOINT, BODY)

  expect(res).toEqual({ status: 'conflict' })
})

it('collapses other failures to error (retry on next sign-in)', async () => {
  mockFetchOnce(async () => ({ ok: false, status: 503, json: async () => ({}) }))
  expect(await exchangeOAuthToken(ENDPOINT, BODY)).toEqual({ status: 'error' })

  mockFetchOnce(async () => {
    throw new Error('network down')
  })
  expect(await exchangeOAuthToken(ENDPOINT, BODY)).toEqual({ status: 'error' })
})

it('treats a 200 without an access token as error', async () => {
  mockFetchOnce(async () => ({ ok: true, status: 200, json: async () => ({}) }))
  expect(await exchangeOAuthToken(ENDPOINT, BODY)).toEqual({ status: 'error' })
})
