/**
 * lib/rsendFetch.ts — Thin wrapper around fetch for RSend backend calls.
 *
 * Adds:
 *  - X-Idempotency-Key header on POST/PUT (UUID v4, prevents double-processing)
 *  - Structured error parsing: { error: "CODE", message: "...", detail: "..." }
 */

/** Generate a UUID v4 idempotency key */
export function idempotencyKey(): string {
  return crypto.randomUUID()
}

/** Parse a structured RSend error response, or return a generic message */
export async function parseRSendError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    // Structured format: { error: "CODE", message: "...", detail: "..." }
    if (body?.error && body?.message) {
      return body.detail
        ? `${body.message} — ${body.detail}`
        : body.message
    }
    // Legacy format: { detail: "..." }
    if (body?.detail) {
      return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    }
    return `HTTP ${res.status}`
  } catch {
    return `HTTP ${res.status} ${res.statusText}`
  }
}

/**
 * Build headers for a mutating request (POST/PUT/DELETE).
 * Merges caller headers with idempotency key.
 */
export function mutationHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Idempotency-Key': idempotencyKey(),
    ...extra,
  }
}
