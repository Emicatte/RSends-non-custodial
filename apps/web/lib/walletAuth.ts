'use client'

/**
 * lib/walletAuth.ts — Session-HMAC wallet auth for the RSends backend (H4).
 *
 * Anti-replay scheme (replaces the old replayable `RSends:{address}:{timestamp}`
 * bearer signature):
 *  1. The wallet signs ONCE `RSends:session:{nonce}:{timestamp}` (one popup) and
 *     exchanges it at POST /api/v1/auth/wallet-session for a short-lived
 *     `session_secret` (Redis-backed, 15 min TTL).
 *  2. Every request carries a SINGLE-USE HMAC over `{nonce}:{timestamp}` keyed by
 *     the session secret. The secret is never transmitted again; a captured MAC
 *     cannot be reused (nonce is single-use server-side) or forged.
 *
 * `signOnce` is unchanged — it signs arbitrary operation-specific messages used
 * by callers (e.g. forwarding/split mutations) and is NOT the request credential.
 *
 * Cache + dedupe scope: GLOBAL SINGLETON via globalThis + Symbol.for (Next.js
 * dynamic imports inline this module into multiple chunks; see the original
 * rationale). The cached unit is now the session (secret + imported HMAC key),
 * not a reusable signature.
 */

import { useCallback, useEffect, useRef } from 'react'
import { useSignMessage } from 'wagmi'

const SESSION_SAFETY_MS = 30_000 // refresh ~30 s before the backend TTL (900 s)
const SIGN_TIMEOUT_MS = 60_000
const BACKEND = '/api/backend' // same-origin proxy → backend

export interface WalletAuthHeaders {
  'X-Wallet-Address': string
  'X-Wallet-Session': string
  'X-Wallet-Nonce': string
  'X-Timestamp': string
  'X-Wallet-MAC': string
  // Index signature required to satisfy `HeadersInit` (fetch overload).
  [key: string]: string
}

interface WalletSession {
  sessionId: string
  key: CryptoKey // imported HMAC-SHA256 key (the secret never leaves here)
  address: string
  expiresAt: number
}

// ── Global singleton state (shared across bundler chunks) ──────
const GLOBAL_STATE_KEY = Symbol.for('rsends.walletAuth.state.v2')
type GlobalAuthState = {
  sessionMap: Map<string, WalletSession>
  inflightSessionMap: Map<string, Promise<WalletSession>>
  signingPromiseMap: Map<string, Promise<string>>
}
const _g = globalThis as unknown as Record<symbol, GlobalAuthState>
if (!_g[GLOBAL_STATE_KEY]) {
  _g[GLOBAL_STATE_KEY] = {
    sessionMap: new Map(),
    inflightSessionMap: new Map(),
    signingPromiseMap: new Map(),
  }
}
const { sessionMap, inflightSessionMap, signingPromiseMap } = _g[GLOBAL_STATE_KEY]

function _hex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

async function _importHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  )
}

export function useWalletAuth(address: string | undefined) {
  const { signMessageAsync } = useSignMessage()
  const prevAddressRef = useRef<string | undefined>(undefined)

  const clearCache = useCallback(() => {
    if (!address) return
    const key = address.toLowerCase()
    sessionMap.delete(key)
    inflightSessionMap.delete(key)
  }, [address])

  // Drop OLD address state on switch/disconnect (idempotent across hooks).
  useEffect(() => {
    const prev = prevAddressRef.current
    if (prev !== undefined && prev !== address) {
      const prevKey = prev.toLowerCase()
      sessionMap.delete(prevKey)
      inflightSessionMap.delete(prevKey)
      signingPromiseMap.delete(prevKey)
    }
    prevAddressRef.current = address
  }, [address])

  // signOnce — UNCHANGED. Signs an arbitrary message once (cross-hook dedupe),
  // used by callers for operation-specific signatures (not the auth credential).
  const signOnce = useCallback(
    async (message: string): Promise<string> => {
      if (!address) throw new Error('Wallet not connected')
      const key = address.toLowerCase()
      const inflight = signingPromiseMap.get(key)
      if (inflight) return inflight

      const timeout = new Promise<never>((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                'Signature timed out — open your wallet and approve the pending request',
              ),
            ),
          SIGN_TIMEOUT_MS,
        ),
      )
      const promise = Promise.race([signMessageAsync({ message }), timeout])
      signingPromiseMap.set(key, promise)
      try {
        return await promise
      } finally {
        signingPromiseMap.delete(key)
      }
    },
    [address, signMessageAsync],
  )

  // ensureSession — sign ONCE to obtain an HMAC session secret from the backend.
  // Cross-hook dedupe so concurrent callers share ONE signature popup + session.
  const ensureSession = useCallback(async (): Promise<WalletSession> => {
    if (!address) throw new Error('Wallet not connected')
    const key = address.toLowerCase()

    const cached = sessionMap.get(key)
    if (cached && Date.now() < cached.expiresAt) return cached

    const inflight = inflightSessionMap.get(key)
    if (inflight) return inflight

    const promise: Promise<WalletSession> = (async () => {
      const nonce = crypto.randomUUID()
      const ts = new Date().toISOString()
      const signature = await signOnce(`RSends:session:${nonce}:${ts}`)
      const res = await fetch(`${BACKEND}/api/v1/auth/wallet-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Wallet-Address': address,
          'X-Wallet-Signature': signature,
          'X-Timestamp': ts,
        },
        body: JSON.stringify({ nonce }),
        signal: AbortSignal.timeout(15000),
      })
      if (!res.ok) throw new Error(`wallet-session HTTP ${res.status}`)
      const data = await res.json()
      const session: WalletSession = {
        sessionId: data.session_id,
        key: await _importHmacKey(data.session_secret),
        address: key,
        expiresAt: Date.now() + (data.expires_in ?? 900) * 1000 - SESSION_SAFETY_MS,
      }
      sessionMap.set(key, session)
      return session
    })()
    inflightSessionMap.set(key, promise)
    try {
      return await promise
    } finally {
      inflightSessionMap.delete(key)
    }
  }, [address, signOnce])

  // getAuthHeaders — UNCHANGED call signature. Returns a FRESH single-use
  // HMAC credential per call (no wallet popup; the HMAC is computed locally).
  const getAuthHeaders = useCallback(async (): Promise<WalletAuthHeaders> => {
    if (!address) throw new Error('Wallet not connected')
    const session = await ensureSession()
    const nonce = crypto.randomUUID()
    const ts = new Date().toISOString()
    const mac = _hex(
      await crypto.subtle.sign('HMAC', session.key, new TextEncoder().encode(`${nonce}:${ts}`)),
    )
    return {
      'X-Wallet-Address': address,
      'X-Wallet-Session': session.sessionId,
      'X-Wallet-Nonce': nonce,
      'X-Timestamp': ts,
      'X-Wallet-MAC': mac,
    }
  }, [address, ensureSession])

  return { signOnce, getAuthHeaders, clearCache }
}
