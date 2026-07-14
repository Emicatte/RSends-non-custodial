/**
 * bearerAdminAuthorized — the single implementation of the Bearer ADMIN_SECRET
 * fallback (password-only, no 2FA). Pins the M11 rule that 2fa/setup was
 * missing: in production the bearer is refused unless ADMIN_ALLOW_BEARER=1,
 * even when the secret is correct.
 */
import { bearerAdminAuthorized } from '@/lib/auth/adminTokens'

const SECRET = 'test-admin-secret-value'

describe('bearerAdminAuthorized', () => {
  const origEnv = process.env

  beforeEach(() => {
    process.env = { ...origEnv, ADMIN_SECRET: SECRET }
    delete process.env.ADMIN_ALLOW_BEARER
  })

  afterAll(() => {
    process.env = origEnv
  })

  function setNodeEnv(value: string) {
    Object.defineProperty(process.env, 'NODE_ENV', { value, configurable: true })
  }

  it('accepts the correct bearer outside production', () => {
    setNodeEnv('development')
    expect(bearerAdminAuthorized(`Bearer ${SECRET}`)).toBe(true)
  })

  it('rejects a wrong bearer outside production', () => {
    setNodeEnv('development')
    expect(bearerAdminAuthorized('Bearer wrong-secret')).toBe(false)
  })

  it('rejects a missing/malformed header', () => {
    setNodeEnv('development')
    expect(bearerAdminAuthorized(null)).toBe(false)
    expect(bearerAdminAuthorized('')).toBe(false)
    expect(bearerAdminAuthorized(SECRET)).toBe(false) // no "Bearer " prefix
  })

  it('rejects everything when ADMIN_SECRET is unset', () => {
    setNodeEnv('development')
    delete process.env.ADMIN_SECRET
    expect(bearerAdminAuthorized('Bearer ')).toBe(false)
    expect(bearerAdminAuthorized('Bearer anything')).toBe(false)
  })

  it('REFUSES the correct bearer in production (M11 — the 2fa/setup gap)', () => {
    setNodeEnv('production')
    expect(bearerAdminAuthorized(`Bearer ${SECRET}`)).toBe(false)
  })

  it('accepts the correct bearer in production only with ADMIN_ALLOW_BEARER=1', () => {
    setNodeEnv('production')
    process.env.ADMIN_ALLOW_BEARER = '1'
    expect(bearerAdminAuthorized(`Bearer ${SECRET}`)).toBe(true)
    expect(bearerAdminAuthorized('Bearer wrong-secret')).toBe(false)
  })
})
