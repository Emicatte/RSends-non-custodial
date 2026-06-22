'use client'

// NON-CUSTODIAL: the Classic sweep/forwarding stats endpoints
// (/api/v1/forwarding/stats*) were removed with the custodial backend. This hook
// is kept as an INERT stub (same interface) so the landing pages that still
// reference it compile and render empty — no network calls, no 404s.
// TODO(cleanup): remove the landing "sweep stats" widget and delete this hook.

export interface SweepStats {
  period: string
  total_sweeps: number
  completed: number
  failed: number
  total_volume_eth: number
  total_volume_usd: number
  total_gas_spent_eth: number
  avg_sweep_time_sec: number | null
  success_rate: number
}

export interface DailyPoint {
  date: string
  sweep_count: number
  volume_eth: number
  volume_usd: number
  gas_total: number
}

export function useSweepStats(_address: string | undefined) {
  return {
    stats: null as SweepStats | null,
    daily: [] as DailyPoint[],
    loading: false,
    refresh: () => {},
    backendOffline: false,
  }
}
