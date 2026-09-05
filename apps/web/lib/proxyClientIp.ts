import type { NextRequest } from 'next/server'
import { getClientIp } from '@/lib/rateLimit'

/**
 * The address this proxy observed for the browser, plus the proof that the hop
 * is ours, for the backend's `get_real_client_ip`.
 *
 * Why a secret rather than a CIDR allowlist: the backend can only trust
 * forwarded headers from a network it recognises, and this app's egress IPs
 * rotate — there is nothing stable to put in the backend's TRUSTED_PROXIES for
 * this hop. The backend's own URL is also reachable directly, so trusting the
 * leftmost X-Forwarded-For entry would let anyone with curl pick their own
 * rate-limit bucket and forge audit rows. The shared INTERNAL_PROXY_SECRET
 * identifies the hop instead.
 *
 * The IP is DERIVED via getClientIp — platform-set sources first, and the
 * X-Forwarded-For chain read from the right — never copied from a header the
 * browser controls. Returns {} when no secret is configured: an unprovable
 * claim is dropped by the backend anyway, and sending one only produces a
 * permanent mismatch warning there.
 */
export function clientIpHeaders(req: NextRequest): Record<string, string> {
  const secret = process.env.INTERNAL_PROXY_SECRET
  if (!secret) return {}

  return {
    'X-RSend-Client-IP': getClientIp(req),
    'X-RSend-Proxy-Secret': secret,
  }
}
