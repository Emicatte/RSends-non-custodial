'use client'

/**
 * Client-side helpers for the staged-onboarding session endpoints, via the
 * existing apiCall (Bearer + one-shot cookie refresh on 401).
 */

import { apiCall } from '@/lib/auth-client'
import type {
  CompanyProfile,
  CompanyProfilePatch,
  OnboardingState,
} from '@/lib/onboarding'

export function getOnboardingState(accessToken: string | undefined) {
  return apiCall<OnboardingState>('/api/v1/user/onboarding', accessToken)
}

export function postConsents(accessToken: string | undefined) {
  return apiCall<OnboardingState>('/api/v1/user/consents', accessToken, {
    method: 'POST',
    body: JSON.stringify({ accept_documents: true, age_attested: true }),
  })
}

export function getCompanyProfile(accessToken: string | undefined) {
  return apiCall<CompanyProfile>('/api/v1/user/org/company-profile', accessToken)
}

export function patchCompanyProfile(
  accessToken: string | undefined,
  patch: CompanyProfilePatch,
) {
  return apiCall<CompanyProfile>('/api/v1/user/org/company-profile', accessToken, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function submitCompanyProfile(accessToken: string | undefined) {
  return apiCall<CompanyProfile>(
    '/api/v1/user/org/company-profile/submit',
    accessToken,
    { method: 'POST' },
  )
}
