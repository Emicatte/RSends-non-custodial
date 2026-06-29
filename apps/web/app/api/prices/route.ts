/**
 * app/api/prices/route.ts — decoupled EUR/USD price feed.
 *
 * One internal endpoint the client always calls. `PRICE_SOURCE` selects the
 * upstream: `public` (default) → keyless frankfurter.app ECB rate; `backend` →
 * proxy the existing FastAPI /api/v1/prices. Short server-side cache; stale cache
 * is served if the upstream blips, otherwise a clean 502 PRICE_SOURCE_UNREACHABLE
 * — never an unhandled throw. (Mirrors app/api/backend/[...path] + tokens-market.)
 */
import { NextResponse } from 'next/server'
import { publicSource } from '@/lib/prices/publicSource'
import { backendSource } from '@/lib/prices/backendSource'
import type { PricesResult } from '@/lib/prices/types'

const TTL = 5 * 60 * 1000
let cache: PricesResult | null = null

export async function GET() {
  if (cache && Date.now() - cache.ts < TTL) {
    return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=300' } })
  }

  const source = process.env.PRICE_SOURCE === 'backend' ? backendSource : publicSource
  try {
    cache = await source.fetchRates()
    return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=300' } })
  } catch (err) {
    if (cache) {
      return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=60' } })
    }
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: 'PRICE_SOURCE_UNREACHABLE', message }, { status: 502 })
  }
}
