'use client';

import { useEffect, useRef, useState } from 'react';
import { getCached, getStaleCache, setCached, fetchWithDedup } from '@/lib/coingeckoCache';

type UseCoinGeckoOptions = {
  ttlMs: number;
  refreshIntervalMs?: number;
  enabled?: boolean;
};

type State<T> = {
  data: T | null;
  error: Error | null;
  stale: boolean;
  loading: boolean;
};

export function useCoinGecko<T>(
  url: string | null,
  cacheKey: string,
  options: UseCoinGeckoOptions
): State<T> {
  const { ttlMs, refreshIntervalMs, enabled = true } = options;
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    stale: false,
    loading: true,
  });
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled || !url) {
      setState((s) => ({ ...s, loading: false }));
      return;
    }

    let cancelled = false;
    const run = async () => {
      // Try cache first
      const cached = getCached<T>(cacheKey);
      if (cached) {
        if (!cancelled && mountedRef.current) {
          setState({ data: cached, error: null, stale: false, loading: false });
        }
        return;
      }

      try {
        const data = await fetchWithDedup<T>(url);
        setCached(cacheKey, data, ttlMs);
        if (!cancelled && mountedRef.current) {
          setState({ data, error: null, stale: false, loading: false });
        }
      } catch (err) {
        const stale = getStaleCache<T>(cacheKey);
        if (!cancelled && mountedRef.current) {
          setState({
            data: stale,
            error: err as Error,
            stale: stale !== null,
            loading: false,
          });
        }
      }
    };

    run();

    // Refresh interval
    let interval: NodeJS.Timeout | null = null;
    if (refreshIntervalMs) {
      interval = setInterval(() => {
        if (document.visibilityState === 'visible') run();
      }, refreshIntervalMs);
    }

    // Refetch on visibility
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        const cached = getCached<T>(cacheKey);
        if (!cached) run();
      }
    };
    document.addEventListener('visibilitychange', onVis);

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [url, cacheKey, ttlMs, refreshIntervalMs, enabled]);

  return state;
}
