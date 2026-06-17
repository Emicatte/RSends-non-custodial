/**
 * useIdempotencyKey — Genera un X-Idempotency-Key unico per ogni tentativo di TX.
 * Inviato al backend per prevenire doppie esecuzioni.
 */
import { useCallback, useRef } from 'react'

export function useIdempotencyKey() {
  const keyRef = useRef<string>('')

  const generateKey = useCallback(() => {
    keyRef.current = crypto.randomUUID()
    return keyRef.current
  }, [])

  const getKey = useCallback(() => keyRef.current, [])

  return { generateKey, getKey }
}
