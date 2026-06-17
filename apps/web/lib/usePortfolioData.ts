
import { useState, useEffect, useCallback, useRef } from 'react'

export interface PortfolioAsset {
  symbol:          string
  name:            string
  balance:         number
  decimals:        number
  usdValue:        number
  contractAddress: string
}

export interface ActivityItem {
  hash:      string
  from:      string
  to:        string
  value:     number
  asset:     string
  category:  string
  timestamp: string | null
}

export interface BalancePoint {
  date:  string
  value: number
}

export interface PortfolioData {
  address:        string
  chainId:        number
  totalUsd:       number
  assets:         PortfolioAsset[]
  activity:       ActivityItem[]
  balanceHistory: BalancePoint[]
  updatedAt:      string
}

export type PortfolioStatus = 'idle' | 'loading' | 'success' | 'error'

export function usePortfolioData(address: string | undefined, chainId: number) {
  const [data, setData]       = useState<PortfolioData | null>(null)
  const [status, setStatus]   = useState<PortfolioStatus>('idle')
  const [error, setError]     = useState<string | null>(null)
  const intervalRef           = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchPortfolio = useCallback(async (isRefresh = false) => {
    if (!address) return
    if (!isRefresh) setStatus('loading')

    try {
      const res = await fetch(`/api/portfolio/${address}?chainId=${chainId}`, {
        signal: AbortSignal.timeout(15000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setStatus('success')
      setError(null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      if (!isRefresh) setStatus('error')
    }
  }, [address, chainId])

  // Initial fetch + on address/chain change
  useEffect(() => {
    if (!address) { setData(null); setStatus('idle'); return }
    fetchPortfolio(false)
  }, [address, chainId, fetchPortfolio])

  // Auto-refresh every 60s
  useEffect(() => {
    if (!address) return
    intervalRef.current = setInterval(() => fetchPortfolio(true), 60_000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [address, chainId, fetchPortfolio])

  return { data, status, error, refresh: () => fetchPortfolio(false) }
}