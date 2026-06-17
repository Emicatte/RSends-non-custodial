import { useRef, useState, useCallback } from 'react'

/**
 * Hook that guarantees an async action executes ONCE at a time.
 * Prevents double-click, re-render triggers, and race conditions.
 *
 * Uses a ref-based gate (synchronous, immune to React batching)
 * plus reactive state for UI (isLoading, error).
 *
 * @example
 * const { execute, isLoading, error } = useGuardedAction(async (ruleId: number) => {
 *   await fetch(`/api/rules/${ruleId}`, { method: 'DELETE' });
 * });
 * <button onClick={() => execute(rule.id)} disabled={isLoading}>Delete</button>
 */
export function useGuardedAction<TArgs extends any[], TResult = void>(
  action: (...args: TArgs) => Promise<TResult>,
  options?: {
    onSuccess?: (result: TResult) => void
    onError?: (error: Error) => void
    onUserRejected?: () => void
    timeoutMs?: number
  }
) {
  const isRunningRef = useRef(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const execute = useCallback(async (...args: TArgs): Promise<TResult | undefined> => {
    if (isRunningRef.current) {
      console.warn('[useGuardedAction] Blocked duplicate execution')
      return undefined
    }

    isRunningRef.current = true
    setIsLoading(true)
    setError(null)

    const timeoutMs = options?.timeoutMs ?? 30_000
    let timer: ReturnType<typeof setTimeout> | null = null

    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Action timed out')), timeoutMs)
      })
      const result = await Promise.race([action(...args), timeout])
      options?.onSuccess?.(result)
      return result
    } catch (err: any) {
      const wrapped = err instanceof Error ? err : new Error(String(err))

      const isUserRejection =
        err?.code === 4001 ||
        err?.code === 'ACTION_REJECTED' ||
        /user (rejected|denied|cancelled)/i.test(err?.message ?? '')

      if (isUserRejection) {
        options?.onUserRejected?.()
      } else {
        setError(wrapped)
        options?.onError?.(wrapped)
      }

      return undefined
    } finally {
      if (timer) clearTimeout(timer)
      isRunningRef.current = false
      setIsLoading(false)
    }
  }, [action, options])

  const reset = useCallback(() => {
    setError(null)
    setIsLoading(false)
    isRunningRef.current = false
  }, [])

  return { execute, isLoading, error, reset }
}
