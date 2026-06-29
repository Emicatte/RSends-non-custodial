/**
 * lib/prices/types.ts — price-source abstraction.
 *
 * The client always calls the internal `/api/prices` route; the route picks a
 * source by `PRICE_SOURCE` env. Rates are EUR-based ({ EUR: 1, USD: <rate> }) and
 * used ONLY for display (EUR-equivalent of token amounts) — never to compute the
 * charged on-chain fee.
 */
export interface PricesResult {
  base: 'EUR'
  rates: Record<string, number>
  source: 'public' | 'backend'
  ts: number
}

export interface PriceSource {
  name: 'public' | 'backend'
  fetchRates(): Promise<PricesResult>
}

export class PriceSourceError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PriceSourceError'
  }
}
