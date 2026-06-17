/**
 * requireEnv — read a required server-side env var; throw if missing.
 * Use for vars that must never silently fall back (e.g. backend URLs, secrets).
 */
export function requireEnv(key: string): string {
  const val = process.env[key]
  if (!val) throw new Error(`Missing required env var: ${key}`)
  return val
}
