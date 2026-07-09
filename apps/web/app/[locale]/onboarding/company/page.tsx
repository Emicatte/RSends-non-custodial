'use client'

/**
 * Company info step — unlocks the test dashboard on submit. Draft autosaves
 * server-side (resume across sessions/devices); the backend enforces
 * completeness and the declarations at submit.
 */

import { useTranslations } from 'next-intl'
import { CompanyProfileForm } from '@/components/onboarding/CompanyProfileForm'
import { OnboardingStepIndicator } from '@/components/onboarding/OnboardingStepIndicator'

export default function CompanyInfoPage() {
  const t = useTranslations('onboarding.company')

  return (
    <div className="space-y-10">
      <OnboardingStepIndicator current="companyInfo" />
      <div
        className="rounded-2xl border p-6 md:p-8 space-y-6"
        style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
      >
        <p className="text-sm" style={{ color: '#888780' }}>
          {t('intro')}
        </p>
        <CompanyProfileForm />
      </div>
    </div>
  )
}
