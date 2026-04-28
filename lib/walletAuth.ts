'use client'

/**
 * lib/walletAuth.ts — EIP-191 wallet signature helper for RSends backend auth.
 *
 * Centralizes signOnce + getAuthHeaders previously duplicated across
 * useForwardingRules.ts and useSplitContracts.ts. Used by:
 *  - mutation calls (POST/PUT/DELETE) → pair with mutationHeaders({...auth})
 *  - GET calls under C1 IDOR fix → ownership-checked endpoints
 *
 * Cache: signature reused across calls within a ~4m30s window
 * (5 min backend tolerance - 30 s safety buffer). Cache invalidates
 * automatically when `address` changes (wallet switch / disconnect).
 *
 * Cache + dedupe scope: MODULE-LEVEL (shared across hook instances).
 * Multiple components calling useWalletAuth(address) for the same wallet
 * see ONE signature popup, not N. Two independent dedupe layers:
 *  - inflightAuthMap: getAuthHeaders waiters share the full
 *    {signature, timestamp} tuple. Prevents sig/ts mismatch when
 *    concurrent callers build their own timestamps.
 *  - signingPromiseMap: signOnce-level dedupe for direct mutation
 *    callers. Concurrent mutations on the same address share one
 *    signature instead of queueing two MetaMask popups.
 */

import { useCallback, useEffect, useRef } from 'react'
import { useSignMessage } from 'wagmi'

const SIGNATURE_TTL_MS = 4 * 60_000 + 30_000 // 4 min 30 sec
const SIGN_TIMEOUT_MS = 60_000

export interface WalletAuthHeaders {
  'X-Wallet-Address': string
  'X-Wallet-Signature': string
  'X-Timestamp': string
  // Index signature required to satisfy `HeadersInit` (fetch overload).
  [key: string]: string
}

interface CachedAuth {
  signature: string
  timestamp: string
  expiresAt: number
}

// ── Module-level state (shared across hook instances) ───────────
// Keyed by address.toLowerCase() so different casings of the same
// wallet share entries. Not exported — encapsulated state.
const cacheMap = new Map<string, CachedAuth>()
const inflightAuthMap = new Map<string, Promise<CachedAuth>>()
const signingPromiseMap = new Map<string, Promise<string>>()

function toHeaders(address: string, auth: CachedAuth): WalletAuthHeaders {
  return {
    'X-Wallet-Address': address,
    'X-Wallet-Signature': auth.signature,
    'X-Timestamp': auth.timestamp,
  }
}

export function useWalletAuth(address: string | undefined) {
  const { signMessageAsync } = useSignMessage()

  // Track previous address so we can drop its cache on switch/disconnect.
  const prevAddressRef = useRef<string | undefined>(undefined)

  const clearCache = useCallback(() => {
    if (!address) return
    cacheMap.delete(address.toLowerCase())
  }, [address])

  // Drop OLD address state on switch/disconnect.
  // Idempotent across hooks: if hook A already deleted, hook B
  // detecting the same change later just no-ops.
  useEffect(() => {
    const prev = prevAddressRef.current
    if (prev !== undefined && prev !== address) {
      const prevKey = prev.toLowerCase()
      cacheMap.delete(prevKey)
      inflightAuthMap.delete(prevKey)
      signingPromiseMap.delete(prevKey)
    }
    prevAddressRef.current = address
  }, [address])

  const signOnce = useCallback(async (message: string): Promise<string> => {
    if (!address) throw new Error('Wallet not connected')
    const key = address.toLowerCase()

    // Cross-hook dedupe: if another caller is already signing for this
    // address, return the same promise. Note: dedupe ignores message
    // content — concurrent callers with different messages all receive
    // the first signature. Acceptable here because every caller signs
    // `RSends:{address}:{...}` for the same connected wallet.
    const inflight = signingPromiseMap.get(key)
    if (inflight) return inflight

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(
        'Signature timed out — open your wallet and approve the pending request'
      )), SIGN_TIMEOUT_MS)
    )
    const promise = Promise.race([signMessageAsync({ message }), timeout])
    signingPromiseMap.set(key, promise)
    try {
      return await promise
    } finally {
      signingPromiseMap.delete(key)
    }
  }, [address, signMessageAsync])

  const getAuthHeaders = useCallback(async (): Promise<WalletAuthHeaders> => {
    if (!address) throw new Error('Wallet not connected')
    const key = address.toLowerCase()

    // Cache hit
    const cached = cacheMap.get(key)
    if (cached && Date.now() < cached.expiresAt) {
      return toHeaders(address, cached)
    }

    // In-flight dedupe (cross-hook, cross-call): waiters share the full
    // {signature, timestamp} tuple, so all consumers get a CONSISTENT
    // pair (avoids backend 401 from sig/ts mismatch on a naive design).
    const inflight = inflightAuthMap.get(key)
    if (inflight) return toHeaders(address, await inflight)

    // Cold path: build timestamp + sign + populate cache
    const promise: Promise<CachedAuth> = (async () => {
      const timestamp = new Date().toISOString()
      const message = `RSends:${address}:${timestamp}`
      const signature = await signOnce(message)
      const auth: CachedAuth = {
        signature,
        timestamp,
        expiresAt: Date.now() + SIGNATURE_TTL_MS,
      }
      cacheMap.set(key, auth)
      return auth
    })()
    inflightAuthMap.set(key, promise)
    try {
      return toHeaders(address, await promise)
    } finally {
      inflightAuthMap.delete(key)
    }
  }, [address, signOnce])

  return { signOnce, getAuthHeaders, clearCache }
}
