import { NextRequest, NextResponse } from 'next/server'

/**
 * POST /api/paymaster/{network}
 *
 * L3 — server-side proxy for the Pimlico bundler/paymaster JSON-RPC. Keeps
 * PIMLICO_API_KEY OUT of the client bundle: the browser calls this same-origin
 * route (no key) and we attach the key here. The JSON-RPC body is passed
 * through verbatim.
 */
const ALLOWED_NETWORKS = new Set(['base', 'base-sepolia'])

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ network: string }> },
) {
  const { network } = await params
  if (!ALLOWED_NETWORKS.has(network)) {
    return NextResponse.json({ error: 'UNSUPPORTED_NETWORK' }, { status: 400 })
  }

  const apiKey = process.env.PIMLICO_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'PAYMASTER_NOT_CONFIGURED' }, { status: 503 })
  }

  const body = await req.text() // pass the JSON-RPC payload through verbatim

  try {
    const upstream = await fetch(
      `https://api.pimlico.io/v2/${network}/rpc?apikey=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        signal: AbortSignal.timeout(10_000),
      },
    )
    const text = await upstream.text()
    return new NextResponse(text, {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    return NextResponse.json(
      { error: 'PAYMASTER_UNREACHABLE', message: String(err) },
      { status: 502 },
    )
  }
}
