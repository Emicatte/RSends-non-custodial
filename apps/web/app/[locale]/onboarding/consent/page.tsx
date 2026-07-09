'use client'

/**
 * Consent interstitial — the only authenticated page a session without
 * current consents / age attestation can reach (server-enforced by the
 * layout guard on /app and /settings). Catches OAuth signups and existing
 * users after a document-version bump.
 */

import { useTranslations } from 'next-intl'
import { ConsentForm } from '@/components/onboarding/ConsentForm'
import { OnboardingStepIndicator } from '@/components/onboarding/OnboardingStepIndicator'

export default function ConsentPage() {
  const t = useTranslations('onboarding.consent')

  return (
    <div className="space-y-10">
      <OnboardingStepIndicator current="account" />
      <div
        className="rounded-2xl border p-6 md:p-8 space-y-4"
        style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
      >
        <h1 className="text-xl font-semibold" style={{ color: '#0A0A0A' }}>
          {t('heading')}
        </h1>
        <p className="text-sm" style={{ color: '#888780' }}>
          {t('body')}
        </p>
        <ConsentForm />
      </div>
    </div>
  )
}
