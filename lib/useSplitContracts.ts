'use client'

/**
 * useSplitContracts — React hook per il sistema N-wallet SplitContract.
 *
 * Wraps gli endpoint backend `/api/v1/splits/*` (S2/S3) che coesistono
 * col sistema legacy `/api/v1/forwarding/rules` (2-way split).
 *
 * ⚠️ IMPORTANTE — BPS invariants:
 *   - share_bps sono INTERI, 10000 = 100.00%
 *   - La somma degli share_bps deve essere ESATTAMENTE 10000
 *   - Questa regola è enforced sia client-side (pre-send guard) che
 *     backend-side (Pydantic validator + split_engine.validate_recipients)
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { mutationHeaders, parseRSendError } from './rsendFetch'
import { useWalletAuth } from './walletAuth'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'

// ═══════════════════════════════════════════════════════════
//  TYPES
// ═══════════════════════════════════════════════════════════

export type SplitRole = 'primary' | 'commission' | 'fee' | 'recipient'

export interface SplitRecipientInput {
  wallet_address: string
  label?: string
  role?: SplitRole
  share_bps: number       // 1..10000 (integer)
  position?: number
}

export interface SplitRecipient {
  id: number
  wallet_address: string
  label: string
  role: SplitRole
  share_bps: number
  share_percent: string   // "95.00%" — pre-formattato dal backend
  position: number
  is_active: boolean
}

export interface SplitContract {
  id: number
  client_id: string
  client_name: string
  contract_ref: string
  version: number
  master_wallet: string
  chain_id: number
  chain_family: string
  allowed_tokens: string[]
  rsend_fee_bps: number
  is_active: boolean
  is_locked: boolean
  superseded_by: number | null
  created_at: string | null
  locked_at: string | null
  deactivated_at: string | null
  recipients?: SplitRecipient[]
  recipient_count?: number
  total_bps?: number
}

export interface CreateSplitContractPayload {
  client_id: string
  client_name?: string
  contract_ref?: string
  master_wallet: string
  chain_id: number
  recipients: SplitRecipientInput[]
  rsend_fee_bps?: number
  allowed_tokens?: string[]
}

export interface SimulateSplitPayload {
  amount: string          // umano: "100.00"
  token: string           // "USDC"
  decimals: number
  recipients: SplitRecipientInput[]
  rsend_fee_bps?: number
}

export interface SimulatedRecipient {
  wallet: string
  label: string
  role: string
  share_percent: string
  share_bps: number
  amount_raw: string
  amount_human: string
  position: number
}

export interface SimulationResult {
  simulation: true
  input: { amount_raw: string; amount_human: string; token: string }
  rsend_fee: { amount_raw: string; amount_human: string; bps: number }
  distributable: { amount_raw: string; amount_human: string }
  recipients: SimulatedRecipient[]
  remainder_raw: string
  check_passed: boolean
}

export interface SplitExecution {
  id: number
  contract_id: number
  source_tx_hash: string
  input_amount: string
  input_token: string
  input_decimals: number
  status: string          // pending | executing | completed | partial_failure | failed
  total_distributed: string | null
  rsend_fee: string | null
  remainder: string | null
  distribution_detail: Array<{
    wallet: string
    label: string
    share_bps: number
    amount: string
    tx_hash: string | null
    status: string
    error?: string
  }> | null
  started_at: string | null
  completed_at: string | null
}

// ═══════════════════════════════════════════════════════════
//  BPS guard (client-side defense)
// ═══════════════════════════════════════════════════════════

function assertBpsSumExact(recipients: SplitRecipientInput[]): void {
  if (recipients.length < 2) {
    throw new Error('At least 2 recipients required for a split contract')
  }
  if (recipients.length > 20) {
    throw new Error('Maximum 20 recipients allowed')
  }
  const total = recipients.reduce((s, r) => s + (r.share_bps | 0), 0)
  if (total !== 10000) {
    throw new Error(`Recipients share_bps must sum to exactly 10000, got ${total}`)
  }
  for (const r of recipients) {
    if (!Number.isInteger(r.share_bps) || r.share_bps <= 0 || r.share_bps > 10000) {
      throw new Error(`Invalid share_bps: ${r.share_bps}`)
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  HOOK
// ═══════════════════════════════════════════════════════════

export function useSplitContracts(address: string | undefined) {
  const [contracts, setContracts] = useState<SplitContract[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const failCountRef = useRef(0)
  const [backendOffline, setBackendOffline] = useState(false)

  const { signOnce, getAuthHeaders, clearCache } = useWalletAuth(address)

  // ── client_id derivation ──────────────────────────────
  // Usiamo l'owner address come client_id (stabile, unique per utente).
  // È anche la stessa stringa usata per `master_wallet` — l'address riceve
  // il pagamento e il backend splitta verso i recipients.
  const clientId = address?.toLowerCase() || null

  // ── List contracts (scoped to connected wallet) ───────
  const fetchContracts = useCallback(async (silent = false) => {
    if (!clientId) {
      setContracts([])
      return
    }
    if (!silent) setLoading(true)
    try {
      const url = `${BACKEND}/api/v1/splits/contracts?client_id=${clientId}&active_only=false`
      const doFetch = async () => {
        const headers = await getAuthHeaders()
        return fetch(url, { headers, signal: AbortSignal.timeout(15000) })
      }
      let res = await doFetch()
      if (res.status === 401) {
        clearCache()
        res = await doFetch()
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setContracts(Array.isArray(data?.contracts) ? data.contracts : [])
      setError(null)
      failCountRef.current = 0
      setBackendOffline(false)
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : String(e))
      failCountRef.current++
      if (failCountRef.current >= 5) setBackendOffline(true)
    }
    if (!silent) setLoading(false)
  }, [clientId, getAuthHeaders, clearCache])

  useEffect(() => { fetchContracts() }, [fetchContracts])

  // Soft refresh every 30s when wallet connected
  useEffect(() => {
    if (!clientId) return
    const iv = setInterval(() => fetchContracts(true), 30000)
    return () => clearInterval(iv)
  }, [clientId, fetchContracts])

  // ── Create contract ───────────────────────────────────
  const createContract = useCallback(async (
    payload: CreateSplitContractPayload
  ): Promise<SplitContract> => {
    assertBpsSumExact(payload.recipients)

    if (!address) throw new Error('Wallet not connected')
    const isoTimestamp = new Date().toISOString()
    const message = `RSends:${address}:${isoTimestamp}`
    const signature = await signOnce(message)

    const body: CreateSplitContractPayload = {
      ...payload,
      master_wallet: payload.master_wallet.toLowerCase(),
      rsend_fee_bps: payload.rsend_fee_bps ?? 50,
      allowed_tokens: payload.allowed_tokens ?? [],
      recipients: payload.recipients.map((r, i) => ({
        wallet_address: r.wallet_address.toLowerCase(),
        label: r.label ?? '',
        role: r.role ?? 'recipient',
        share_bps: r.share_bps | 0,
        position: r.position ?? i,
      })),
    }

    const res = await fetch(`${BACKEND}/api/v1/splits/contracts`, {
      method: 'POST',
      headers: mutationHeaders({
        'X-Wallet-Address': address,
        'X-Wallet-Signature': signature,
        'X-Timestamp': isoTimestamp,
      }),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) throw new Error(await parseRSendError(res))
    const data = await res.json()
    await fetchContracts(true)
    return data?.contract as SplitContract
  }, [address, fetchContracts, signOnce])

  // ── Get contract detail ───────────────────────────────
  const getContract = useCallback(async (contractId: number): Promise<SplitContract> => {
    const doFetch = async () => {
      const headers = await getAuthHeaders()
      return fetch(
        `${BACKEND}/api/v1/splits/contracts/${contractId}`,
        { headers, signal: AbortSignal.timeout(10000) },
      )
    }
    let res = await doFetch()
    if (res.status === 401) {
      clearCache()
      res = await doFetch()
    }
    if (!res.ok) throw new Error(await parseRSendError(res))
    const data = await res.json()
    return data?.contract as SplitContract
  }, [getAuthHeaders, clearCache])

  // ── Deactivate contract ───────────────────────────────
  const deactivateContract = useCallback(async (contractId: number) => {
    if (!address) throw new Error('Wallet not connected')
    const isoTimestamp = new Date().toISOString()
    const message = `RSends:${address}:${isoTimestamp}`
    const signature = await signOnce(message)

    const res = await fetch(
      `${BACKEND}/api/v1/splits/contracts/${contractId}/deactivate`,
      {
        method: 'POST',
        headers: mutationHeaders({
          'X-Wallet-Address': address,
          'X-Wallet-Signature': signature,
          'X-Timestamp': isoTimestamp,
        }),
        signal: AbortSignal.timeout(10000),
      }
    )
    if (!res.ok) throw new Error(await parseRSendError(res))
    await fetchContracts(true)
    return res.json()
  }, [address, fetchContracts, signOnce])

  // ── Simulate split (preview) ──────────────────────────
  // NO state-change: questa chiamata è pura, usabile per preview live nel wizard.
  const simulateSplit = useCallback(async (
    payload: SimulateSplitPayload
  ): Promise<SimulationResult> => {
    assertBpsSumExact(payload.recipients)

    const body: SimulateSplitPayload = {
      ...payload,
      rsend_fee_bps: payload.rsend_fee_bps ?? 50,
      recipients: payload.recipients.map((r, i) => ({
        wallet_address: r.wallet_address.toLowerCase(),
        label: r.label ?? '',
        role: r.role ?? 'recipient',
        share_bps: r.share_bps | 0,
        position: r.position ?? i,
      })),
    }

    const res = await fetch(`${BACKEND}/api/v1/splits/simulate`, {
      method: 'POST',
      headers: mutationHeaders(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    })
    if (!res.ok) throw new Error(await parseRSendError(res))
    return res.json() as Promise<SimulationResult>
  }, [])

  // ── List executions (audit trail) ─────────────────────
  const listExecutions = useCallback(async (
    contractId: number,
    limit = 20,
  ): Promise<SplitExecution[]> => {
    const doFetch = async () => {
      const headers = await getAuthHeaders()
      return fetch(
        `${BACKEND}/api/v1/splits/contracts/${contractId}/executions?limit=${limit}`,
        { headers, signal: AbortSignal.timeout(10000) },
      )
    }
    let res = await doFetch()
    if (res.status === 401) {
      clearCache()
      res = await doFetch()
    }
    if (!res.ok) throw new Error(await parseRSendError(res))
    const data = await res.json()
    return Array.isArray(data?.executions) ? data.executions : []
  }, [getAuthHeaders, clearCache])

  return {
    contracts,
    loading,
    error,
    backendOffline,
    clientId,
    refresh: () => fetchContracts(),
    createContract,
    getContract,
    deactivateContract,
    simulateSplit,
    listExecutions,
  }
}
