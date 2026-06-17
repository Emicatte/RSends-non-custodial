'use client'

import { useEffect, useState, useRef } from 'react'
import type { TokenMarket } from '@/lib/types/tokenMarket'

const POLL_MS = 30_000

export function useMarketDataLive(refreshMs = POLL_MS) {
  const [data, setData] = useState<Record<string, TokenMarket>>({})
  const [loading, setLoading] = useState(true)
  const mountedRef = useRef(true)
  const lastFetchRef = useRef(0)

  useEffect(() => {
    mountedRef.current = true
    let interval: ReturnType<typeof setInterval> | null = null

    const fetchData = async () => {
      try {
        const res = await fetch('/api/tokens-market')
        if (!res.ok) throw new Error(`tokens-market ${res.status}`)
        const json = await res.json()
        if (mountedRef.current && json && typeof json === 'object') {
          setData(json as Record<string, TokenMarket>)
          lastFetchRef.current = Date.now()
        }
      } catch {
        // Keep last successful data — never clear on error
      } finally {
        if (mountedRef.current) setLoading(false)
      }
    }

    // Initial fetch
    fetchData()

    // Start polling
    const startPolling = () => {
      if (interval) clearInterval(interval)
      interval = setInterval(() => {
        if (document.visibilityState === 'visible') fetchData()
      }, refreshMs)
    }
    startPolling()

    // Pause/resume on visibility change
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        // Fetch immediately if stale
        if (Date.now() - lastFetchRef.current > refreshMs) fetchData()
        startPolling()
      } else {
        if (interval) clearInterval(interval)
        interval = null
      }
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      mountedRef.current = false
      if (interval) clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [refreshMs])

  return { data, loading }
}
