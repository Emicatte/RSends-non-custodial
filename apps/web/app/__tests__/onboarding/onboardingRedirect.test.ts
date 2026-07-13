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

  it('routes a pending merchant to the waiting screen (never /app)', () => {
    expect(
      resolveOnboardingRedirect(state({ approval_status: 'pending_approval' }), 'en'),
    ).toBe('/en/onboarding/pending')
    // Unknown/missing approval state fails closed to the waiting screen too.
    expect(
      resolveOnboardingRedirect(state({ approval_status: null }), 'en'),
    ).toBe('/en/onboarding/pending')
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
