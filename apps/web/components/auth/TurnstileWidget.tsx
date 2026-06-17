'use client'

import { useEffect, useRef } from 'react'

// Minimal typing for the Cloudflare Turnstile global.
interface TurnstileAPI {
  render: (
    el: HTMLElement,
    opts: {
      sitekey: string
      theme?: 'light' | 'dark' | 'auto'
      callback?: (token: string) => void
      'error-callback'?: () => void
      'expired-callback'?: () => void
    },
  ) => string
  remove: (id: string) => void
  reset: (id?: string) => void
}

declare global {
  interface Window {
    turnstile?: TurnstileAPI
  }
}

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? ''
const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

function loadTurnstile(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return resolve()
    if (window.turnstile) return resolve()
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('turnstile_script')))
      if (window.turnstile) resolve()
      return
    }
    const s = document.createElement('script')
    s.src = SCRIPT_SRC
    s.async = true
    s.defer = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('turnstile_script'))
    document.head.appendChild(s)
  })
}

/**
 * Cloudflare Turnstile widget. Calls `onToken(token)` when solved, and
 * `onToken(null)` on error/expiry so the parent can gate submit. Renders
 * nothing if NEXT_PUBLIC_TURNSTILE_SITE_KEY is unset.
 */
export function TurnstileWidget({
  onToken,
  theme = 'light',
}: {
  onToken: (token: string | null) => void
  theme?: 'light' | 'dark' | 'auto'
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetId = useRef<string | null>(null)
  // Keep the latest callback without re-rendering the widget on each parent render.
  const cb = useRef(onToken)
  cb.current = onToken

  useEffect(() => {
    if (!SITE_KEY) return
    let cancelled = false

    loadTurnstile()
      .then(() => {
        if (cancelled || !containerRef.current || !window.turnstile) return
        if (widgetId.current !== null) return // guard against double-invoke (StrictMode)
        widgetId.current = window.turnstile.render(containerRef.current, {
          sitekey: SITE_KEY,
          theme,
          callback: (token: string) => cb.current(token),
          'error-callback': () => cb.current(null),
          'expired-callback': () => cb.current(null),
        })
      })
      .catch(() => cb.current(null))

    return () => {
      cancelled = true
      if (widgetId.current !== null && window.turnstile) {
        try {
          window.turnstile.remove(widgetId.current)
        } catch {
          /* widget already gone */
        }
        widgetId.current = null
      }
    }
  }, [theme])

  if (!SITE_KEY) return null
  return <div ref={containerRef} />
}
