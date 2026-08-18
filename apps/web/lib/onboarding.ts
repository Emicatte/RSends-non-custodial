/**
 * Staged-onboarding state types + the pure redirect decision.
 *
 * PURE module (no client/server-only imports): `resolveOnboardingRedirect`
 * is shared by the server layout guard (lib/onboarding-guard.ts) and the
 * client gate page (/onboarding). Consents and the 18+ attestation come
 * first, then the company-profile step; submitting the profile is the last
 * gate before the dashboard. The session API helpers live in
 * lib/onboarding-client.ts (client-only, via apiCall).
 */

/**
 * The aggregate onboarding-state endpoint. Single-sourced so the server guard
 * (lib/onboarding-guard.ts) and the client probe (lib/onboarding-client.ts,
 * which the retry gate re-asks as "the guard's exact question") cannot drift
 * onto different paths.
 */
export const ONBOARDING_ENDPOINT = '/api/v1/user/onboarding'

export interface CompanyProfileState {
  exists: boolean
  submitted_at: string | null
}

export interface OnboardingState {
  consents_current: boolean
  age_attested: boolean
  email_verified: boolean
  active_org_id: string | null
  onboarding_status: 'created' | 'email_verified' | 'company_submitted' | null
  activation_status: string | null
  approval_status: 'pending_approval' | 'approved' | 'declined' | null
  decline_reason: string | null
  company_profile: CompanyProfileState | null
}

export interface CompanyProfile {
  legal_name: string | null
  trading_name: string | null
  country: string | null
  registration_number: string | null
  tax_or_vat_number: string | null
  website: string | null
  business_category: string | null
  expected_monthly_volume: string | null
  countries_served: string[] | null
  primary_stablecoin: string | null
  no_sanctioned_countries: boolean | null
  no_prohibited_activities: boolean | null
  has_pep: boolean | null
  submitted_at: string | null
}

export type CompanyProfilePatch = Partial<Omit<CompanyProfile, 'submitted_at'>>

/**
 * Where must this session go? `null` = fully onboarded, proceed.
 */
export function resolveOnboardingRedirect(
  state: OnboardingState,
  locale: string,
): string | null {
  if (!state.consents_current || !state.age_attested) {
    return `/${locale}/onboarding/consent`
  }
  if (state.onboarding_status !== 'company_submitted') {
    return `/${locale}/onboarding/company`
  }
  // An explicit operator decline still stops here — it is a decision, not a
  // queue position.
  if (state.approval_status === 'declined') {
    return `/${locale}/onboarding/declined`
  }
  // `pending_approval` reaches the dashboard (2026-08-08). The submitted
  // company profile IS the gate for the sandbox, and /app is hard-locked to
  // testnet, so a pending merchant gets a working dashboard and a working
  // sandbox key with no operator in the loop. The backend agrees — see
  // deps/approval_policy.py; the old 403-from-every-widget hazard this branch
  // guarded against no longer exists.
  //
  // The waiting screen (/onboarding/pending) is intentionally kept: it is the
  // right destination again when mainnet activation ships, where real approval
  // is required. Route to it from the live-activation flow, not from here.
  return null
}
