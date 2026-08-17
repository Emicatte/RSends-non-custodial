/**
 * resolveOnboardingRedirect — the pure decision the server layout guard and
 * the client gate page both apply:
 *   consents/age not current  → /{locale}/onboarding/consent
 *   org not company_submitted → /{locale}/onboarding/company
 *   fully onboarded           → null (proceed to the dashboard)
 */
import { resolveOnboardingRedirect, type OnboardingState } from '@/lib/onboarding'

function state(overrides: Partial<OnboardingState> = {}): OnboardingState {
  return {
    consents_current: true,
    age_attested: true,
    email_verified: true,
    active_org_id: 'org-1',
    onboarding_status: 'company_submitted',
    activation_status: 'not_started',
    approval_status: 'approved',
    decline_reason: null,
    company_profile: { exists: true, submitted_at: '2026-07-09T00:00:00Z' },
    ...overrides,
  }
}

describe('resolveOnboardingRedirect', () => {
  it('returns null for a fully onboarded session', () => {
    expect(resolveOnboardingRedirect(state(), 'en')).toBeNull()
  })

  it('routes to the consent step when consents are stale', () => {
    expect(
      resolveOnboardingRedirect(state({ consents_current: false }), 'en'),
    ).toBe('/en/onboarding/consent')
  })

  it('routes to the consent step when age is not attested', () => {
    expect(
      resolveOnboardingRedirect(state({ age_attested: false }), 'it'),
    ).toBe('/it/onboarding/consent')
  })

  it('consent step wins over company step (ordering)', () => {
    expect(
      resolveOnboardingRedirect(
        state({ consents_current: false, onboarding_status: 'email_verified' }),
        'en',
      ),
    ).toBe('/en/onboarding/consent')
  })

  it('routes to the company step pre-submission (dashboard redirect)', () => {
    expect(
      resolveOnboardingRedirect(state({ onboarding_status: 'email_verified' }), 'en'),
    ).toBe('/en/onboarding/company')
    expect(
      resolveOnboardingRedirect(state({ onboarding_status: 'created' }), 'en'),
    ).toBe('/en/onboarding/company')
  })

  it('routes to the company step when the org is not resolved yet', () => {
    expect(
      resolveOnboardingRedirect(
        state({ active_org_id: null, onboarding_status: null, company_profile: null }),
        'en',
      ),
    ).toBe('/en/onboarding/company')
  })

  it('lets a pending merchant into the dashboard once KYB is submitted', () => {
    // 2026-08-08: the submitted company profile IS the sandbox gate. A merchant
    // waiting on manual approval still gets /app (test-locked) and a working
    // sandbox key — no operator in the loop. Backend agrees: the `test` branch
    // of services/backend/app/api/deps/approval_policy.py.
    expect(
      resolveOnboardingRedirect(state({ approval_status: 'pending_approval' }), 'en'),
    ).toBeNull()
    expect(
      resolveOnboardingRedirect(state({ approval_status: null }), 'en'),
    ).toBeNull()
  })

  it('still stops a declined merchant before the dashboard', () => {
    expect(
      resolveOnboardingRedirect(state({ approval_status: 'declined' }), 'en'),
    ).not.toBeNull()
  })

  it('routes a declined merchant to the decline page', () => {
    expect(
      resolveOnboardingRedirect(
        state({ approval_status: 'declined', decline_reason: 'nope' }),
        'it',
      ),
    ).toBe('/it/onboarding/declined')
  })
})
