import { publicSource } from '@/lib/prices/publicSource'
import { PriceSourceError } from '@/lib/prices/types'

function mockFetchOnce(impl: () => Promise<Partial<Response>>) {
  ;(global as unknown as { fetch: jest.Mock }).fetch = jest.fn(impl as never)
}

const okJson = (body: unknown): Partial<Response> => ({
  ok: true,
  status: 200,
  json: async () => body,
})

describe('publicSource (frankfurter)', () => {
  afterEach(() => jest.restoreAllMocks())

  it('maps the ECB EUR/USD rate', async () => {
    mockFetchOnce(async () => okJson({ amount: 1, base: 'EUR', rates: { USD: 1.08 } }))
    const res = await publicSource.fetchRates()
    expect(res).toMatchObject({ base: 'EUR', source: 'public', rates: { EUR: 1, USD: 1.08 } })
    expect(typeof res.ts).toBe('number')
  })

  it('throws PriceSourceError on a non-ok response', async () => {
    mockFetchOnce(async () => ({ ok: false, status: 503, json: async () => ({}) }))
    await expect(publicSource.fetchRates()).rejects.toBeInstanceOf(PriceSourceError)
  })

  it('throws PriceSourceError when the rate is missing', async () => {
    mockFetchOnce(async () => okJson({ rates: {} }))
    await expect(publicSource.fetchRates()).rejects.toBeInstanceOf(PriceSourceError)
  })
})
