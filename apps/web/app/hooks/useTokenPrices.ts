'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { getAllCoingeckoIds } from '../tokens/tokenRegistry'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'
const COINGECKO_API = '/api/market'
const REFRESH_INTERVAL = 30_000 // 30 secondi — prezzi più reattivi

export interface TokenPrices {
  [coingeckoId: string]: { eur: number; usd: number; usd_24h_change?: number }
}

/**
 * Fetch prezzi via proxy CoinGecko interno `/api/market` (COINGECKO_API).
 * Non chiama CoinGecko direttamente: il proxy server-side inietta
 * COINGECKO_API_KEY e applica il rate-limit, così la key non finisce mai
 * nel bundle client. Usato come fallback quando il backend RPagos non risponde.
 */
async function fetchFromCoinGecko(): Promise<TokenPrices> {
  const ids = getAllCoingeckoIds().join(',')
  const res = await fetch(
    `${COINGECKO_API}/simple/price?ids=${ids}&vs_currencies=eur,usd&include_24hr_change=true`,
  )
  if (!res.ok) throw new Error(`CoinGecko ${res.status}`)
  const data: Record<string, { eur?: number; usd?: number; usd_24h_change?: number }> = await res.json()

  const merged: TokenPrices = {}
  for (const [id, vals] of Object.entries(data)) {
    merged[id] = {
      eur: vals.eur ?? 0,
      usd: vals.usd ?? 0,
      usd_24h_change: typeof vals.usd_24h_change === 'number' ? vals.usd_24h_change : undefined,
    }
  }
  return merged
}

/**
 * Fetch dal backend RPagos (che proxya CoinGecko con Redis cache).
 */
async function fetchFromBackend(): Promise<TokenPrices> {
  const res = await fetch(`${BACKEND}/api/v1/prices`)
  if (!res.ok) throw new Error(`Backend ${res.status}`)
  const data = await res.json()
  const eur: Record<string, number> = data.eur ?? {}
  const usd: Record<string, number> = data.usd ?? {}
  const usd24h: Record<string, number> = data.usd_24h_change ?? {}

  const merged: TokenPrices = {}
  const allIds = new Set([...Object.keys(eur), ...Object.keys(usd)])
  for (const id of allIds) {
    merged[id] = {
      eur: eur[id] ?? 0,
      usd: usd[id] ?? 0,
      usd_24h_change: typeof usd24h[id] === 'number' ? usd24h[id] : undefined,
    }
  }
  return merged
}

/**
 * Hook che fetcha i prezzi real-time ogni 30 secondi.
 * Prova il backend prima, poi fallback sul proxy CoinGecko interno (/api/market).
 */
export function useTokenPrices() {
  const [prices, setPrices] = useState<TokenPrices>({})
  const [isLoading, setIsLoading] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchPrices = useCallback(async () => {
    try {
      // Try backend first (has Redis cache, lower latency)
      const data = await fetchFromBackend()
      setPrices(data)
    } catch {
      // Backend down — fetch directly from CoinGecko
      try {
        const data = await fetchFromCoinGecko()
        setPrices(data)
      } catch {
        // Both failed — keep stale prices
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPrices()
    intervalRef.current = setInterval(fetchPrices, REFRESH_INTERVAL)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchPrices])

  return { prices, isLoading, refetch: fetchPrices }
}
