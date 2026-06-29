import { publicSource } from '@/lib/prices/publicSource'
import { backendSource } from '@/lib/prices/backendSource'
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

describe('backendSource', () => {
  const ORIGINAL = process.env.RPAGOS_BACKEND_URL
  afterEach(() => {
    jest.restoreAllMocks()
    process.env.RPAGOS_BACKEND_URL = ORIGINAL
  })

  it('maps eur_usd from the backend feed', async () => {
    process.env.RPAGOS_BACKEND_URL = 'http://backend.test'
    mockFetchOnce(async () => okJson({ eur_usd: 1.07 }))
    const res = await backendSource.fetchRates()
    expect(res).toMatchObject({ base: 'EUR', source: 'backend', rates: { EUR: 1, USD: 1.07 } })
  })

  it('tolerates a { rates: { USD } } shape', async () => {
    process.env.RPAGOS_BACKEND_URL = 'http://backend.test'
    mockFetchOnce(async () => okJson({ rates: { USD: 1.05 } }))
    const res = await backendSource.fetchRates()
    expect(res.rates.USD).toBe(1.05)
  })

  it('throws PriceSourceError when RPAGOS_BACKEND_URL is unset', async () => {
    delete process.env.RPAGOS_BACKEND_URL
    await expect(backendSource.fetchRates()).rejects.toBeInstanceOf(PriceSourceError)
  })
})
