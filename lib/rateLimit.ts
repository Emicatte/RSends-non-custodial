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

/**
 * Extract the real client IP. Vercel-aware:
 *   - x-real-ip: canonical on Vercel, set by their edge layer.
 *   - x-forwarded-for: comma-separated chain; first entry is the
 *     real client when behind a trusted proxy.
 */
export function getClientIp(req: NextRequest): string {
  return (
    req.headers.get('x-real-ip') ||
    req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    '127.0.0.1'
  )
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
