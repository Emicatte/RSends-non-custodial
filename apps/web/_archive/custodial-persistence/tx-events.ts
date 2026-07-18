'use client'

import type { CreateTxPayload } from '@/hooks/useUserTransactions'

export interface TxSubmittedEvent extends CreateTxPayload {
  clientId: string
}

export interface TxConfirmedEvent {
  clientId: string
  tx_hash: string
  chain_id: number
  tx_status: 'confirmed' | 'failed' | 'cancelled'
  gas_used?: number
  gas_price_gwei?: string
  block_number?: number
  confirmed_at?: string
}

export function emitTxSubmitted(detail: TxSubmittedEvent) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent<TxSubmittedEvent>('rsends:tx-submitted', { detail }),
  )
}

export function emitTxConfirmed(detail: TxConfirmedEvent) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent<TxConfirmedEvent>('rsends:tx-confirmed', { detail }),
  )
}
