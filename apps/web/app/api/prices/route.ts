/**
 * app/api/prices/route.ts — decoupled EUR/USD price feed.
 *
 * One internal endpoint the client always calls, one upstream behind it: the
 * keyless frankfurter.app ECB rate. Short server-side cache; stale cache is
 * served if the upstream blips, otherwise a clean 502 PRICE_SOURCE_UNREACHABLE
 * — never an unhandled throw. (Mirrors app/api/backend/[...path] + tokens-market.)
 *
 * There used to be a `PRICE_SOURCE=backend` branch proxying the FastAPI
 * /api/v1/prices feed. That feed is gone (the dashboard now values stablecoins
 * from a static peg), and the branch had never worked anyway: its extractor
 * accepted four response shapes and the feed returned none of them.
 */
import { NextResponse } from 'next/server'
import { publicSource } from '@/lib/prices/publicSource'
import type { PricesResult } from '@/lib/prices/types'

const TTL = 5 * 60 * 1000
let cache: PricesResult | null = null

export async function GET() {
  if (cache && Date.now() - cache.ts < TTL) {
    return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=300' } })
  }

  try {
    cache = await publicSource.fetchRates()
    return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=300' } })
  } catch (err) {
    if (cache) {
      return NextResponse.json(cache, { headers: { 'Cache-Control': 'public, max-age=60' } })
    }
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: 'PRICE_SOURCE_UNREACHABLE', message }, { status: 502 })
  }
}
