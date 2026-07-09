'use client'

/**
 * Consent interstitial form — the two required checkboxes (combined
 * ToS+Privacy acceptance linking both documents, and the 18+ attestation).
 * Submit stays disabled until both are ticked; acceptance is recorded
 * server-side (POST /api/v1/user/consents) and the form routes onward from
 * the returned state. Server-side enforcement lives in the /app and
 * /settings layout guard — this page is just how a session satisfies it.
 */

import { useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { Link, useRouter } from '@/i18n/navigation'
import { postConsents } from '@/lib/onboarding-client'

export function ConsentForm() {
  const t = useTranslations('onboarding.consent')
  const router = useRouter()
  const { data: session } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token

  const [documentsAccepted, setDocumentsAccepted] = useState(false)
  const [ageAttested, setAgeAttested] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(false)

  const canSubmit = documentsAccepted && ageAttested && !submitting

  const onSubmit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(false)
    try {
      const state = await postConsents(accessToken)
      router.replace(
        state.onboarding_status === 'company_submitted'
          ? '/app'
          : '/onboarding/company',
      )
    } catch {
      setError(true)
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-5">
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={documentsAccepted}
          onChange={(e) => setDocumentsAccepted(e.target.checked)}
          className="mt-1 h-4 w-4 shrink-0 accent-[#C8512C]"
        />
        <span className="text-sm" style={{ color: '#2C2C2A' }}>
          {t.rich('documents', {
            termsLink: (chunks) => (
              <Link
                href="/docs/terms"
                target="_blank"
                className="underline"
                style={{ color: '#C8512C' }}
              >
                {chunks}
              </Link>
            ),
            privacyLink: (chunks) => (
              <Link
                href="/docs/privacy"
                target="_blank"
                className="underline"
                style={{ color: '#C8512C' }}
              >
                {chunks}
              </Link>
            ),
          })}
        </span>
      </label>

      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={ageAttested}
          onChange={(e) => setAgeAttested(e.target.checked)}
          className="mt-1 h-4 w-4 shrink-0 accent-[#C8512C]"
        />
        <span className="text-sm" style={{ color: '#2C2C2A' }}>
          {t('age')}
        </span>
      </label>

      {error && (
        <p className="text-sm" role="alert" style={{ color: '#B3261E' }}>
          {t('error')}
        </p>
      )}

      <button
        type="button"
        disabled={!canSubmit}
        onClick={onSubmit}
        className="w-full rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ background: '#C8512C' }}
      >
        {t('submit')}
      </button>
    </div>
  )
}
