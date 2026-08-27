/**
 * Login failure taxonomy.
 *
 * Every distinct way logging in can fail gets its own code, so the UI can tell
 * the truth about what happened. The rule that motivates this module: the
 * "authentication service temporarily unavailable" copy must be reachable ONLY
 * from a genuine upstream failure. It was previously a catch-all, and on
 * 2026-08-26 it told a user the service was down while the backend was serving
 * other logins successfully in the same second.
 *
 * Deliberate constraints:
 *   • A 401 always collapses to `invalid_credentials`, whatever body code the
 *     backend sent. An unknown email and a wrong password MUST be
 *     indistinguishable — enumeration protection is not negotiable.
 *   • Nothing here retries. Blind retries on an auth endpoint are a rate-limit
 *     and account-lockout hazard.
 *   • Every failure carries a correlation id, sent upstream as X-Request-ID /
 *     X-Correlation-ID so a browser-side report can be joined to the backend's
 *     request log and `auth_audit_log.correlation_id`.
 */

/** The shape `backendLogin` throws: a response-derived failure. */
export interface RawLoginFailure {
  code?: string
  message?: string
  status?: number
  retry_after?: string | null
}

export interface LoginFailure {
  code: string
  message?: string
  status?: number
  retry_after?: string | null
  correlationId: string
}

/**
 * A UUID, because the backend's request-context middleware regenerates
 * X-Request-ID unless the inbound value parses as one — a non-UUID id would be
 * silently dropped and the join would not exist.
 */
export function newCorrelationId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  // Older Safari / non-secure contexts: same shape, weaker entropy. Only ever
  // used to correlate logs, never as a secret or a lookup key.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function isAbort(err: unknown): boolean {
  const name = (err as { name?: string } | null)?.name
  return name === 'TimeoutError' || name === 'AbortError'
}

/**
 * Map a thrown value from the login call onto exactly one user-facing code.
 *
 * A value with no numeric `status` never reached a responding server (fetch
 * rejected: offline, DNS, TLS, CORS) — that is the client's side of the wire,
 * never an upstream outage.
 */
export function classifyLoginFailure(
  err: unknown,
  correlationId: string,
): LoginFailure {
  if (isAbort(err)) return { code: 'request_timeout', correlationId }

  const raw = err as RawLoginFailure | null
  const status = typeof raw?.status === 'number' ? raw.status : undefined

  if (status === undefined) return { code: 'network_error', correlationId }

  // The only legitimate producer of the service-unavailable copy.
  if (status >= 500) return { code: 'auth_unavailable', status, correlationId }

  if (status === 429) {
    return {
      code: 'rate_limit_exceeded',
      status,
      retry_after: raw?.retry_after ?? null,
      correlationId,
    }
  }

  // Collapsed on purpose — see the enumeration note above.
  if (status === 401) {
    return { code: 'invalid_credentials', status, correlationId }
  }

  // Everything else is a specific, safe-to-surface backend code
  // (account_suspended, account_deleted, password_not_set, …). A 2xx reaching
  // here means the body was not the login payload, and `backendLogin` has
  // already labelled that `auth_unavailable`.
  return {
    code: raw?.code || 'unknown',
    message: raw?.message,
    status,
    correlationId,
  }
}

/**
 * The only client-side record of an auth failure. There is no Sentry in this
 * app; without this line a browser failure leaves no trace at all, which is
 * why the 2026-08-26 incident could not be tied to a backend request.
 */
export function logLoginFailure(failure: LoginFailure): void {
  console.error('[auth] login failed', {
    correlationId: failure.correlationId,
    code: failure.code,
    status: failure.status ?? null,
  })
}
