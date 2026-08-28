'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { apiCall } from '@/lib/auth-client'

/**
 * Session-authed org volume series — `GET /api/v1/user/org/stats/volume-series`.
 *
 * Feeds the /app "Volume trend" card. Deliberately a SEPARATE hook from
 * `useOrgStats` and deliberately UNPOLLED: `useOrgStats` refetches every 30s,
 * and a 7-day settlement scan with per-row USD pricing has no business running
 * on that cadence. A daily trend does not move between polls; it reloads on
 * mount and on an active-org switch, which is when it can actually change.
 *
 * Hard-locked to the `test` environment (no `environment` param → the backend's
 * `test` default), matching the rest of /app: mainnet routers are undeployed,
 * so there is no live data to show and no env toggle in the UI.
 */

export interface VolumeSeriesBucket {
  /** Bare UTC calendar date, `YYYY-MM-DD`. */
  date: string
  volume_usd: number
  /**
   * Settlements on this day the backend could not value, and therefore did NOT
   * add to `volume_usd`. A bucket at 0.0 with a non-zero count was not a quiet
   * day — it is the one place a dropped payment can hide in this chart.
   */
  unpriced_count: number
}

export interface VolumeSeriesPayload {
  days: number
  buckets: VolumeSeriesBucket[]
  /** Window total; always equal to the sum of the buckets' counts. */
  unpriced_count: number
}

export function useOrgVolumeSeries(days = 7) {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [buckets, setBuckets] = useState<VolumeSeriesBucket[] | null>(null)
  // Kept beside `buckets` rather than derived from them: the card states the
  // window's exclusion once, and a flat series with a non-zero count is
  // exactly the case the notice exists for.
  const [unpricedCount, setUnpricedCount] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<boolean>(false)
  // Bumped on active-org switch to force a refetch.
  const [nonce, setNonce] = useState<number>(0)

  useEffect(() => {
    tokenRef.current = (session as { access_token?: string } | null)
      ?.access_token
  }, [session])

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const t = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (t) tokenRef.current = t
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [])

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setBuckets(null)
      setUnpricedCount(0)
      setError(false)
      setLoading(false)
      return
    }
    try {
      const data = await apiCall<VolumeSeriesPayload>(
        `/api/v1/user/org/stats/volume-series?days=${days}`,
        tokenRef.current,
      )
      setBuckets(data.buckets ?? [])
      setUnpricedCount(data.unpriced_count ?? 0)
      setError(false)
    } catch (e) {
      setError(true)
      setBuckets(null)
      setUnpricedCount(0)
      console.error('[useOrgVolumeSeries] reload', e)
    } finally {
      setLoading(false)
    }
    // `nonce` is intentionally a dep: an org switch bumps it to refetch.
  }, [status, accessToken, days, nonce])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    const onOrgChange = () => setNonce((n) => n + 1)
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [])

  return {
    buckets,
    unpricedCount,
    loading,
    error,
    isAuthed: status === 'authenticated',
    reload,
  }
}
