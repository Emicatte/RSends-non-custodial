/**
 * Classify a backend response status on the admin-approvals path into a
 * distinct, readable error, or null to pass it through untouched.
 *
 * The bridge injects `X-Admin-Token` server-side and `isAuthorized` has
 * already validated the admin_session cookie before forwarding — so the
 * browser never supplies the token and the caller is always this proxy. A 403
 * from `require_admin` therefore CANNOT mean "wrong caller"; it can only mean
 * the configured proxy token does not match the backend's. Surface that
 * instead of a bare 403 that reads identically to an access denial.
 *
 * Kept in its own module (no `next/server` import) so it is unit-testable in
 * jsdom without the edge Request polyfill.
 */
export function mapAdminBackendError(
  status: number,
): { error: string; message: string } | null {
  if (status === 403) {
    return {
      error: 'ADMIN_TOKEN_MISMATCH',
      message:
        'Admin token mismatch: BACKEND_ADMIN_API_TOKEN (Vercel) does not match ' +
        'ADMIN_API_TOKEN (Render). Set them identical and redeploy.',
    }
  }
  return null
}
