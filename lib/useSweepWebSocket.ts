'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { requireEnv } from '@/lib/env'

// TODO: WebSocket calls go directly to the backend from the browser.
// Next.js API routes don't proxy WebSockets natively, so this remains
// direct-to-backend for now. Consider migrating to a server-side WS
// proxy (e.g. a Node server or a Vercel Edge function) so the backend
// URL can become server-only.
const BACKEND = requireEnv('NEXT_PUBLIC_RPAGOS_BACKEND_URL')

export interface SweepEvent {
  type: string
  data: Record<string, any>
  timestamp: string
}

export interface WsStats {
  totalEvents: number
  reconnects: number
}

export function useSweepWebSocket(address: string | undefined) {
  const [events, setEvents] = useState<SweepEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [wsStats, setWsStats] = useState<WsStats>({ totalEvents: 0, reconnects: 0 })
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [backendOffline, setBackendOffline] = useState(false)
  const errorLoggedRef = useRef(false)

  const connect = useCallback(() => {
    if (!address) return
    const wsUrl = BACKEND.replace(/^http/, 'ws') + `/ws/sweep-feed/${address}`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setBackendOffline(false)
        retryRef.current = 0
        errorLoggedRef.current = false
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'heartbeat' || msg.type === 'stats') return
          setEvents(prev =>
            [{ type: msg.type, data: msg.data ?? msg, timestamp: msg.timestamp || new Date().toISOString() }, ...prev].slice(0, 50)
          )
          setWsStats(prev => ({ ...prev, totalEvents: prev.totalEvents + 1 }))
        } catch { /* malformed message */ }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        setWsStats(prev => ({ ...prev, reconnects: prev.reconnects + 1 }))
        const attempt = retryRef.current
        retryRef.current++

        if (attempt >= 10) {
          if (!errorLoggedRef.current) {
            console.error('[useSweepWebSocket] Backend offline after 10 attempts')
            errorLoggedRef.current = true
          } else {
            console.debug('[useSweepWebSocket] Still offline, heartbeat retry')
          }
          setBackendOffline(true)
          timerRef.current = setTimeout(connect, 30000)
          return
        }

        const delay = Math.min(2000 * Math.pow(2, attempt), 30000)
        timerRef.current = setTimeout(connect, delay)
      }

      ws.onerror = () => ws.close()
    } catch {
      const attempt = retryRef.current
      retryRef.current++

      if (attempt >= 10) {
        if (!errorLoggedRef.current) {
          console.error('[useSweepWebSocket] Backend offline after 10 attempts')
          errorLoggedRef.current = true
        }
        setBackendOffline(true)
        timerRef.current = setTimeout(connect, 30000)
        return
      }

      const delay = Math.min(2000 * Math.pow(2, attempt), 30000)
      timerRef.current = setTimeout(connect, delay)
    }
  }, [address])

  useEffect(() => {
    connect()
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [connect])

  const reconnect = useCallback(() => {
    if (wsRef.current) wsRef.current.close()
    retryRef.current = 0
    setBackendOffline(false)
    errorLoggedRef.current = false
    connect()
  }, [connect])

  return { events, connected, reconnect, wsStats, backendOffline }
}
