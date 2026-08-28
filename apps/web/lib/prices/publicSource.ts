/**
 * lib/prices/publicSource.ts — keyless ECB EUR/USD from frankfurter.app.
 *
 * The only source behind /api/prices. No API key, short upstream timeout;
 * failures surface as PriceSourceError so the route returns a clean 502.
 */
import { PriceSourceError, type PriceSource, type PricesResult } from './types'

const FRANKFURTER_URL = 'https://api.frankfurter.app/latest?from=EUR&to=USD'

export const publicSource: PriceSource = {
  name: 'public',
  async fetchRates(): Promise<PricesResult> {
    let res: Response
    try {
      res = await fetch(FRANKFURTER_URL, { signal: AbortSignal.timeout(8000), cache: 'no-store' })
    } catch (err) {
      throw new PriceSourceError(err instanceof Error ? err.message : String(err))
    }
    if (!res.ok) throw new PriceSourceError(`frankfurter ${res.status}`)
    const data = (await res.json().catch(() => null)) as { rates?: { USD?: number } } | null
    const usd = data?.rates?.USD
    if (typeof usd !== 'number' || !Number.isFinite(usd)) {
      throw new PriceSourceError('frankfurter: missing EUR/USD rate')
    }
    return { base: 'EUR', rates: { EUR: 1, USD: usd }, source: 'public', ts: Date.now() }
  },
}
