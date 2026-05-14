import { NextRequest, NextResponse } from 'next/server'



const ALCHEMY_KEY = process.env.ALCHEMY_API_KEY ?? ''

const ALCHEMY_URLS: Record<number, string> = {
  8453:  `https://base-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  84532: `https://base-sepolia.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  1:     `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
}

const USD_PRICES: Record<string, number> = {
  ETH: 2150, WETH: 2150, USDC: 1, USDT: 1, EURC: 1.08,
  cbBTC: 95000, WBTC: 95000, DEGEN: 0.003,
}

const KNOWN_LOGOS: Record<string, string> = {
  ETH:   'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
  WETH:  'https://assets.coingecko.com/coins/images/2518/small/weth.png',
  USDC:  'https://assets.coingecko.com/coins/images/6319/small/usdc.png',
  USDT:  'https://assets.coingecko.com/coins/images/325/small/Tether.png',
  EURC:  'https://assets.coingecko.com/coins/images/26045/small/euro-coin.png',
  cbBTC: 'https://assets.coingecko.com/coins/images/40143/small/cbbtc.png',
  WBTC:  'https://assets.coingecko.com/coins/images/7598/small/wrapped_bitcoin_wbtc.png',
  DEGEN: 'https://assets.coingecko.com/coins/images/34515/small/android-chrome-512x512.png',
}

let rpcId = 1
async function alchemyPost(chainId: number, method: string, params: unknown[]) {
  const url = ALCHEMY_URLS[chainId]
  if (!url || !ALCHEMY_KEY) return null
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: rpcId++, method, params }),
    })
    if (!res.ok) return null
    return (await res.json()).result
  } catch { return null }
}

interface EnrichedAsset {
  symbol: string; name: string; balance: number; decimals: number
  usdValue: number; contractAddress: string
  logo: string | null
}

export async function GET(
  req: NextRequest,
  { params }: { params: { address: string } }
) {
  const address = params.address
  const chainId = Number(req.nextUrl.searchParams.get('chainId') ?? '8453')

  if (!address?.startsWith('0x'))
    return NextResponse.json({ error: 'Indirizzo non valido' }, { status: 400 })

  try {
    // 1. ETH + token balances in parallelo
    const [ethHex, tokenResult] = await Promise.all([
      alchemyPost(chainId, 'eth_getBalance', [address, 'latest']),
      alchemyPost(chainId, 'alchemy_getTokenBalances', [address]),
    ])

    const ethBal = Number(ethHex ? BigInt(ethHex) : 0n) / 1e18

    const assets: EnrichedAsset[] = [{
      symbol: 'ETH', name: 'Ethereum', balance: ethBal, decimals: 18,
      usdValue: ethBal * (USD_PRICES.ETH ?? 0),
      contractAddress: '0x0000000000000000000000000000000000000000',
      logo: KNOWN_LOGOS.ETH,
    }]

    // 2. Filtra token con saldo > 0
    const nonZero = (tokenResult?.tokenBalances ?? [])
      .filter((t: { tokenBalance: string }) =>
        t.tokenBalance && t.tokenBalance !== '0x0' && BigInt(t.tokenBalance) > 0n)
      .slice(0, 20) as { contractAddress: string; tokenBalance: string }[]

    // 3. Metadata in PARALLELO
    const enriched = await Promise.all(
      nonZero.map(async (tok): Promise<EnrichedAsset | null> => {
        try {
          const m = await alchemyPost(chainId, 'alchemy_getTokenMetadata', [tok.contractAddress])
          if (!m?.symbol) return null
          const dec = m.decimals ?? 18
          const bal = Number(BigInt(tok.tokenBalance)) / (10 ** dec)
          return {
            symbol: m.symbol, name: m.name ?? m.symbol,
            balance: bal, decimals: dec,
            usdValue: bal * (USD_PRICES[m.symbol] ?? 0),
            contractAddress: tok.contractAddress,
            logo: m.logo ?? KNOWN_LOGOS[m.symbol] ?? null,
          }
        } catch { return null }
      })
    )
    for (const a of enriched) if (a) assets.push(a)

    // 4. Spam filter: mostra solo token noti o con valore > $0.50
    const filtered = assets.filter(a =>
      a.symbol in USD_PRICES || a.usdValue > 0.50
    )

    filtered.sort((a, b) => b.usdValue - a.usdValue)
    const totalUsd = filtered.reduce((s, a) => s + a.usdValue, 0)

    // 4. Transfers (inviati + ricevuti) in parallelo
    const [out, inc] = await Promise.all([
      alchemyPost(chainId, 'alchemy_getAssetTransfers', [{
        fromBlock:'0x0', toBlock:'latest', fromAddress:address,
        category:['external','erc20'], order:'desc', maxCount:'0xA',
      }]),
      alchemyPost(chainId, 'alchemy_getAssetTransfers', [{
        fromBlock:'0x0', toBlock:'latest', toAddress:address,
        category:['external','erc20'], order:'desc', maxCount:'0x5',
      }]),
    ])

    const mapTx = (t: { hash:string; from:string; to:string; value:number; asset:string; category:string; metadata:{blockTimestamp:string} }) => ({
      hash: t.hash, from: t.from, to: t.to, value: t.value??0,
      asset: t.asset??'ETH', category: t.category,
      timestamp: t.metadata?.blockTimestamp ?? null,
    })

    const seen = new Set<string>()
    const activity = [
      ...(out?.transfers??[]).map(mapTx),
      ...(inc?.transfers??[]).map(mapTx),
    ].filter(tx => { if (seen.has(tx.hash)) return false; seen.add(tx.hash); return true })
     .sort((a,b) => {
       if (!a.timestamp||!b.timestamp) return 0
       return new Date(b.timestamp).getTime()-new Date(a.timestamp).getTime()
     }).slice(0, 15)

    // 5. Balance history (simulata)
    const now = Date.now()
    const balanceHistory = Array.from({ length: 168 }, (_, i) => {
      const h = 168 - i
      const noise = Math.sin(i * 0.3 + address.charCodeAt(4)) * 0.05
      return {
        date: new Date(now - h * 3600_000).toISOString(),
        value: Math.max(0, Math.round(totalUsd * (1 + noise - 0.02*(h/168)) * 100) / 100),
      }
    })

    return NextResponse.json({
      address, chainId,
      totalUsd: Math.round(totalUsd * 100) / 100,
      assets: filtered, activity, balanceHistory,
      updatedAt: new Date().toISOString(),
    })
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : String(err) }, { status: 500 })
  }
}