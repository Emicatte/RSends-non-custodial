/**
 * Per-IP rate limiting helpers — in-memory, best-effort.
 *
 * IMPORTANT: Map is per-instance. In Vercel serverless each Lambda may
 * see a fresh instance; this is BEST-EFFORT throttling, not a strict
 * global limit. For strict limits use Redis (out of scope here).
 *
 * Pattern mirrors the inline implementation in
 * app/api/admin/login/route.ts (kept inline for compatibility; this
 * module is the canonical reusable version).
 */

import type { NextRequest } from 'next/server'

export interface RateLimitOptions {
  max: number       // max requests per window
  windowMs: number  // window size in ms
  key?: string      // optional namespace (one Map per limiter)
}

export interface RateLimitResult {
  allowed: boolean
  retryAfter?: number // seconds until next allowed request
}

const stores = new Map<string, Map<string, number[]>>()

// Number of trusted reverse-proxy hops in front of the app. The real client
// is the entry this many positions from the RIGHT of x-forwarded-for (the IP
// the nearest trusted proxy actually observed). Default 1 (single edge proxy).
const TRUSTED_PROXY_HOPS = Math.max(
  1,
  parseInt(process.env.RATELIMIT_TRUSTED_PROXY_HOPS ?? '1', 10) || 1,
)

/**
 * Extract the real client IP from a TRUSTED source only.
 *
 * Security (M5): the previous version trusted the FIRST entry of
 * `x-forwarded-for`, which is fully client-controlled — any caller can rotate
 * it to mint a fresh rate-limit bucket. Because this IP is also forwarded to
 * the backend signing guard as `ip_address`, that spoof evaded the shared
 * per-IP Redis counter too. We now only trust IPs set by the platform/edge:
 *   1. req.ip                 — populated by Vercel, not client-forgeable
 *   2. x-vercel-forwarded-for — set by Vercel's edge
 *   3. x-real-ip              — set by the reverse proxy
 *   4. x-forwarded-for        — only the entry TRUSTED_PROXY_HOPS from the
 *                               RIGHT, never the leftmost client-supplied hop.
 * Falls back to 127.0.0.1 (local/dev).
 */
export function getClientIp(req: NextRequest): string {
  // 1. Platform-set, non-forgeable sources first.
  const platformIp = (req as NextRequest & { ip?: string }).ip
  if (platformIp) return platformIp

  const vercelXff = req.headers.get('x-vercel-forwarded-for')?.split(',')[0]?.trim()
  if (vercelXff) return vercelXff

  const realIp = req.headers.get('x-real-ip')?.trim()
  if (realIp) return realIp

  // 2. Reverse-proxy chain: trust the entry TRUSTED_PROXY_HOPS from the right.
  //    The leftmost entry is attacker-controlled and must NOT be trusted.
  const xff = req.headers.get('x-forwarded-for')
  if (xff) {
    const parts = xff.split(',').map((p) => p.trim()).filter(Boolean)
    if (parts.length > 0) {
      const idx = Math.max(0, parts.length - TRUSTED_PROXY_HOPS)
      return parts[idx]
    }
  }

  return '127.0.0.1'
}

export function checkRateLimit(
  ip: string,
  opts: RateLimitOptions,
): RateLimitResult {
  const namespace = opts.key || 'default'
  let store = stores.get(namespace)
  if (!store) {
    store = new Map<string, number[]>()
    stores.set(namespace, store)
  }
  const now = Date.now()
  const recent = (store.get(ip) || []).filter((t) => t > now - opts.windowMs)
  if (recent.length >= opts.max) {
    const oldest = recent[0]
    const retryAfter = Math.max(
      1,
      Math.ceil((opts.windowMs - (now - oldest)) / 1000),
    )
    return { allowed: false, retryAfter }
  }
  recent.push(now)
  store.set(ip, recent)
  return { allowed: true }
}

/** Test-only utility for resetting state between unit tests. */
export function __resetRateLimits(): void {
  stores.clear()
}
