/**
 * mapAdminBackendError — a 403 on the admin-approvals path is unambiguously a
 * proxy-token mismatch (the bridge injects X-Admin-Token server-side and the
 * admin_session cookie is already validated), so it must surface a distinct
 * readable error rather than a bare 403 that looks like an access denial.
 */
import { mapAdminBackendError } from '@/lib/admin/adminBackendError'

describe('mapAdminBackendError', () => {
  it('maps 403 to a distinct ADMIN_TOKEN_MISMATCH error naming both env vars', () => {
    const out = mapAdminBackendError(403)
    expect(out).not.toBeNull()
    expect(out!.error).toBe('ADMIN_TOKEN_MISMATCH')
    expect(out!.message).toMatch(/BACKEND_ADMIN_API_TOKEN/)
    expect(out!.message).toMatch(/ADMIN_API_TOKEN/)
  })

  it('passes through non-403 statuses untouched (200/404/409/500)', () => {
    expect(mapAdminBackendError(200)).toBeNull()
    expect(mapAdminBackendError(404)).toBeNull()
    expect(mapAdminBackendError(409)).toBeNull()
    expect(mapAdminBackendError(500)).toBeNull()
  })
})
