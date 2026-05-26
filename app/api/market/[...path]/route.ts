import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'

const UPSTREAM_BASE = 'https://api.coingecko.com/api/v3/'

export async function GET(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  const apiKey = process.env.COINGECKO_API_KEY || ''
  const path = (params.path || []).join('/')
  const search = req.nextUrl.search
  const upstream = `${UPSTREAM_BASE}${path}${search}`

  const headers: HeadersInit = { Accept: 'application/json' }
  if (apiKey) headers['x-cg-demo-api-key'] = apiKey

  const res = await fetch(upstream, { headers })
  const body = await res.text()
  return new NextResponse(body, {
    status: res.status,
    headers: {
      'content-type': res.headers.get('content-type') || 'application/json',
      'cache-control': 'no-store',
    },
  })
}
