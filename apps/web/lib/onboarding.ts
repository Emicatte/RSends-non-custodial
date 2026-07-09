/**
 * Staged-onboarding state types + the pure redirect decision.
 *
 * PURE module (no client/server-only imports): `resolveOnboardingRedirect`
 * is shared by the server layout guard (lib/onboarding-guard.ts) and the
 * client gate page (/onboarding). Consents and the 18+ attestation come
 * first, then the company-profile step; only a fully onboarded session
 * reaches the dashboard. The session API helpers live in
 * lib/onboarding-client.ts (client-only, via apiCall).
 */

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
  return null
}
