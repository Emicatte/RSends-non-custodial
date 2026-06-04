import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  // Cross-chain (CCIP) feature flag — paths incompleti non eseguibili in prod
  // finché non pronti. Abilitare con NEXT_PUBLIC_FEATURE_CROSSCHAIN=true.
  if (process.env.NEXT_PUBLIC_FEATURE_CROSSCHAIN !== 'true') {
    return NextResponse.json(
      { error: 'Cross-chain feature not enabled' },
      { status: 501 }
    )
  }

  const body = await req.json()
  const { sender, recipient, token, amount, sourceChainId, destChainId } = body

  // TODO: AML check tramite backend Python
  // Per ora: approva tutto (placeholder)
  const approved = true
  const riskLevel = 'LOW'

  return NextResponse.json({
    approved,
    riskLevel,
    sourceChainId,
    destChainId,
    token,
    amount,
  })
}
