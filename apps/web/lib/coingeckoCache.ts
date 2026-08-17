'use client';

import { COINGECKO_UPSTREAM } from './coingeckoUpstream';

type CacheEntry<T> = {
  data: T;
  timestamp: number;
  ttl: number;
};

const STORAGE_PREFIX = 'rs_gc_';
const MEMORY_CACHE = new Map<string, CacheEntry<any>>();

export function getCached<T>(key: string): T | null {
  const full = STORAGE_PREFIX + key;

  // Check memory first (faster)
  const mem = MEMORY_CACHE.get(full);
  if (mem && Date.now() - mem.timestamp < mem.ttl) {
    return mem.data as T;
  }

  // Check localStorage
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(full);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() - entry.timestamp < entry.ttl) {
      MEMORY_CACHE.set(full, entry);
      return entry.data;
    }
    // Expired
    window.localStorage.removeItem(full);
    MEMORY_CACHE.delete(full);
  } catch {
    return null;
  }
  return null;
}

export function getStaleCache<T>(key: string): T | null {
  const full = STORAGE_PREFIX + key;
  const mem = MEMORY_CACHE.get(full);
  if (mem) return mem.data as T;
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(full);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    return entry.data;
  } catch {
    return null;
  }
}

export function setCached<T>(key: string, data: T, ttlMs: number): void {
  const full = STORAGE_PREFIX + key;
  const entry: CacheEntry<T> = {
    data,
    timestamp: Date.now(),
    ttl: ttlMs,
  };
  MEMORY_CACHE.set(full, entry);
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(full, JSON.stringify(entry));
  } catch {
    // Quota exceeded — purge oldest and retry once
    try {
      const keys = Object.keys(window.localStorage).filter((k) => k.startsWith(STORAGE_PREFIX));
      if (keys.length > 0) {
        window.localStorage.removeItem(keys[0]);
        window.localStorage.setItem(full, JSON.stringify(entry));
      }
    } catch {
      // give up silently
    }
  }
}

// Inflight dedup: same URL pending → return same promise
const INFLIGHT = new Map<string, Promise<any>>();

export async function fetchWithDedup<T>(url: string, timeoutMs = 10_000): Promise<T> {
  if (INFLIGHT.has(url)) return INFLIGHT.get(url)!;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const headers: HeadersInit = { Accept: 'application/json' };

  // Route api.coingecko.com calls through the internal server proxy at
  // /api/market/* so the (now server-only) COINGECKO_API_KEY can be
  // injected without exposing it in the client bundle.
  const COINGECKO_PREFIX = `${COINGECKO_UPSTREAM}/`;
  const fetchUrl = url.startsWith(COINGECKO_PREFIX)
    ? '/api/market/' + url.slice(COINGECKO_PREFIX.length)
    : url;

  const p = fetch(fetchUrl, { signal: controller.signal, headers })
    .then(async (r) => {
      clearTimeout(timeoutId);
      if (!r.ok) {
        const err = new Error(`CoinGecko ${r.status}`);
        (err as any).status = r.status;
        throw err;
      }
      return r.json();
    })
    .finally(() => {
      clearTimeout(timeoutId);
      INFLIGHT.delete(url);
    });

  INFLIGHT.set(url, p);
  return p;
}
