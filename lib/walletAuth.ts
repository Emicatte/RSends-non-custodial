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
 * Dedupe: concurrent callers await the same in-flight signing promise
 * instead of throwing or triggering multiple wallet prompts.
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

export function useWalletAuth(address: string | undefined) {
  const { signMessageAsync } = useSignMessage()

  const cacheRef = useRef<CachedAuth | null>(null)
  const signingPromiseRef = useRef<Promise<string> | null>(null)

  const clearCache = useCallback(() => {
    cacheRef.current = null
  }, [])

  // Invalidate cache on wallet change (switch / disconnect)
  useEffect(() => {
    cacheRef.current = null
  }, [address])

  const signOnce = useCallback(async (message: string): Promise<string> => {
    // Dedupe: if a signature is already in flight, return its promise.
    // Note: dedupe ignores message content — concurrent callers requesting
    // different messages all receive the first signature. Acceptable here
    // because every caller signs `RSends:{address}:{timestamp}` for the
    // same connected wallet within the same render window.
    if (signingPromiseRef.current) return signingPromiseRef.current

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(
        'Signature timed out — open your wallet and approve the pending request'
      )), SIGN_TIMEOUT_MS)
    )
    const promise = Promise.race([signMessageAsync({ message }), timeout])
    signingPromiseRef.current = promise
    try {
      return await promise
    } finally {
      signingPromiseRef.current = null
    }
  }, [signMessageAsync])

  const getAuthHeaders = useCallback(async (): Promise<WalletAuthHeaders> => {
    if (!address) throw new Error('Wallet not connected')

    const now = Date.now()
    const cached = cacheRef.current
    if (cached && now < cached.expiresAt) {
      return {
        'X-Wallet-Address': address,
        'X-Wallet-Signature': cached.signature,
        'X-Timestamp': cached.timestamp,
      }
    }

    const timestamp = new Date().toISOString()
    const message = `RSends:${address}:${timestamp}`
    const signature = await signOnce(message)
    cacheRef.current = {
      signature,
      timestamp,
      expiresAt: now + SIGNATURE_TTL_MS,
    }
    return {
      'X-Wallet-Address': address,
      'X-Wallet-Signature': signature,
      'X-Timestamp': timestamp,
    }
  }, [address, signOnce])

  return { signOnce, getAuthHeaders, clearCache }
}
