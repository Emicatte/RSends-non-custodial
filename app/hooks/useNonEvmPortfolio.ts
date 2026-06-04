'use client'

import { useState, useEffect, useCallback } from 'react'
import { createTronAdapter } from '../../lib/chain-adapters/tron-adapter'
import { createSolanaAdapter } from '../../lib/chain-adapters/solana-adapter'
import type { UniversalBalance, ChainFamily } from '../../lib/chain-adapters/types'

const COINGECKO_IDS: Record<string, string> = {
  TRX: 'tron', SOL: 'solana', USDC: 'usd-coin', USDT: 'tether', WBTC: 'wrapped-bitcoin',
}

const FALLBACK_PRICES: Record<string, number> = {
  TRX: 0.25, SOL: 180, USDC: 1, USDT: 1, WBTC: 95000,
}

async function fetchPrices(): Promise<Record<string, number>> {
  try {
    const ids = Object.values(COINGECKO_IDS).join(',')
    const res = await fetch(
      `/api/market/simple/price?ids=${ids}&vs_currencies=usd`,
      { signal: AbortSignal.timeout(5000) },
    )
    if (!res.ok) return FALLBACK_PRICES
    const data = await res.json()
    const prices: Record<string, number> = {}
    for (const [symbol, cgId] of Object.entries(COINGECKO_IDS)) {
      prices[symbol] = data[cgId]?.usd ?? FALLBACK_PRICES[symbol] ?? 0
    }
    return prices
  } catch {
    return FALLBACK_PRICES
  }
}

export interface NonEvmPortfolio {
  balances: UniversalBalance[]
  totalUsd: number
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useNonEvmPortfolio(
  family: ChainFamily,
  address: string | null,
): NonEvmPortfolio {
  const [balances, setBalances] = useState<UniversalBalance[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!address || family === 'evm') return
    setLoading(true)
    setError(null)
    try {
      const [adapter, prices] = await Promise.all([
        Promise.resolve(family === 'tron' ? createTronAdapter() : createSolanaAdapter()),
        fetchPrices(),
      ])
      const results = await adapter.getAllBalances(address)
      const enriched = results.map(b => ({
        ...b,
        usdValue: (Number(b.formattedBalance) || 0) * (prices[b.token.symbol] ?? 0),
      }))
      setBalances(enriched)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load balances')
    } finally {
      setLoading(false)
    }
  }, [family, address])

  useEffect(() => { load() }, [load])

  const totalUsd = balances.reduce((s, b) => s + (b.usdValue ?? 0), 0)

  return { balances, totalUsd, loading, error, refresh: load }
}
