'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useWalletAuth } from './walletAuth'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'

export interface SweepStats {
  period: string
  total_sweeps: number
  completed: number
  failed: number
  total_volume_eth: number
  total_volume_usd: number
  total_gas_spent_eth: number
  avg_sweep_time_sec: number | null
  success_rate: number
}

export interface DailyPoint {
  date: string
  sweep_count: number
  volume_eth: number
  volume_usd: number
  gas_total: number
}

export function useSweepStats(address: string | undefined) {
  const [stats, setStats] = useState<SweepStats | null>(null)
  const [daily, setDaily] = useState<DailyPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [backendOffline, setBackendOffline] = useState(false)
  const failCountRef = useRef(0)
  const errorLoggedRef = useRef(false)
  const { getAuthHeaders, clearCache } = useWalletAuth(address)

  const fetchStats = useCallback(async (silent = false) => {
    if (!address) return
    if (!silent) setLoading(true)
    try {
      const statsUrl = `${BACKEND}/api/v1/forwarding/stats?period=30d`
      const dailyUrl = `${BACKEND}/api/v1/forwarding/stats/daily?days=30`
      const doFetch = (url: string, headers: Record<string, string>) =>
        fetch(url, { headers, signal: AbortSignal.timeout(15000) })

      // Sign once → reuse the same headers for both parallel fetches.
      // If either returns 401 (stale cache / clock skew), drop cache and
      // retry both with a fresh signature.
      const headers = await getAuthHeaders()
      let [statsRes, dailyRes] = await Promise.all([
        doFetch(statsUrl, headers),
        doFetch(dailyUrl, headers),
      ])
      if (statsRes.status === 401 || dailyRes.status === 401) {
        clearCache()
        const fresh = await getAuthHeaders()
        ;[statsRes, dailyRes] = await Promise.all([
          doFetch(statsUrl, fresh),
          doFetch(dailyUrl, fresh),
        ])
      }
      if (statsRes.ok) setStats(await statsRes.json())
      if (dailyRes.ok) {
        const d = await dailyRes.json()
        setDaily(d.data ?? [])
      }
      failCountRef.current = 0
      errorLoggedRef.current = false
      setBackendOffline(false)
    } catch {
      failCountRef.current++
      if (!errorLoggedRef.current) {
        console.debug('[useSweepStats] Backend unreachable, silencing further errors')
        errorLoggedRef.current = true
      }
      if (failCountRef.current >= 5) setBackendOffline(true)
    }
    if (!silent) setLoading(false)
  }, [address, getAuthHeaders, clearCache])

  useEffect(() => { fetchStats() }, [fetchStats])

  useEffect(() => {
    if (!address) return
    const iv = setInterval(() => fetchStats(true), 30000)
    return () => clearInterval(iv)
  }, [address, fetchStats])

  return { stats, daily, loading, refresh: () => fetchStats(), backendOffline }
}
