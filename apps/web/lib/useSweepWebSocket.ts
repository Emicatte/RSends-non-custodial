'use client'

// NON-CUSTODIAL: the Classic sweep/forwarding WebSocket feed
// (/api/v1/forwarding/sweep-ticket → backend WS) was removed with the custodial
// backend. This hook is kept as an INERT stub (same interface) so the landing
// pages that still reference it compile and render empty — no WS, no 404s.
// TODO(cleanup): remove the landing "sweep events" widget and delete this hook.

export interface SweepEvent {
  type: string
  data: Record<string, any>
  timestamp: string
}

export interface WsStats {
  totalEvents: number
  reconnects: number
}

export function useSweepWebSocket(_address: string | undefined) {
  return {
    events: [] as SweepEvent[],
    connected: false,
    reconnect: () => {},
    wsStats: { totalEvents: 0, reconnects: 0 } as WsStats,
    backendOffline: false,
  }
}
