'use client'

import { useEffect, useState } from 'react'

/**
 * Wall-clock time for use during render, without breaking hydration.
 *
 * `Date.now()` called in a render body is a render-phase impurity: the server
 * pass and the hydration pass read the clock at different instants, so anything
 * derived from it (relative timestamps, "last 24h" windows) can differ between
 * the two — and a text mismatch outside a Suspense boundary makes React discard
 * the server HTML and re-render the entire root on the client.
 *
 * This returns `null` for the server pass AND the first client render — the two
 * that must produce identical markup — then the real clock from the first
 * effect onward, refreshed every `intervalMs`. Callers MUST render a
 * deterministic, absolute fallback while it is `null`; the point is that the
 * value is always shown, never blanked or delayed, only upgraded.
 *
 * The refresh is also a fix in its own right: relative labels previously went
 * stale until the next data poll.
 *
 * @param intervalMs how often to re-read the clock; 0 disables the refresh.
 */
export function useClientNow(intervalMs = 60_000): number | null {
  const [now, setNow] = useState<number | null>(null)

  useEffect(() => {
    setNow(Date.now())
    if (!intervalMs) return
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])

  return now
}
