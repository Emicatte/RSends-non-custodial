/**
 * lib/prices/backendSource.ts — proxy the existing FastAPI price feed.
 *
 * Used when PRICE_SOURCE === 'backend'. Calls GET {RPAGOS_BACKEND_URL}/api/v1/prices
 * server-side (mirroring app/api/backend/[...path]/route.ts). Tolerant of a few
 * response shapes; any failure becomes a PriceSourceError → clean 502.
 */
import { PriceSourceError, type PriceSource, type PricesResult } from './types'

export const backendSource: PriceSource = {
  name: 'backend',
  async fetchRates(): Promise<PricesResult> {
    const raw = process.env.RPAGOS_BACKEND_URL
    if (!raw) throw new PriceSourceError('RPAGOS_BACKEND_URL not configured')
    const base = raw.replace(/\/$/, '')

    let res: Response
    try {
      res = await fetch(`${base}/api/v1/prices`, { signal: AbortSignal.timeout(8000), cache: 'no-store' })
    } catch (err) {
      throw new PriceSourceError(err instanceof Error ? err.message : String(err))
    }
    if (!res.ok) throw new PriceSourceError(`backend ${res.status}`)
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
    const usd = extractEurUsd(data)
    if (usd == null) throw new PriceSourceError('backend: missing EUR/USD rate')
    return { base: 'EUR', rates: { EUR: 1, USD: usd }, source: 'backend', ts: Date.now() }
  },
}

/** Accept { eur_usd }, { rates: { USD } }, { USD } or { usd }. */
function extractEurUsd(data: Record<string, unknown> | null): number | null {
  if (!data) return null
  const rates = data.rates as { USD?: unknown } | undefined
  const candidates: unknown[] = [data.eur_usd, rates?.USD, data.USD, data.usd]
  for (const c of candidates) {
    if (typeof c === 'number' && Number.isFinite(c)) return c
  }
  return null
}
