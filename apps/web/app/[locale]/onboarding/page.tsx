'use client'

/**
 * Onboarding gate page — where the fail-closed server guard sends any session
 * it could not positively confirm (expired access token, post-OAuth exchange
 * window, backend error). Resolves the state client-side via apiCall (which
 * performs the one-shot cookie refresh) and routes to the right step, or back
 * to the dashboard when fully onboarded.
 */

import { useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useRouter } from '@/i18n/navigation'
import { useOnboarding } from '@/hooks/useOnboarding'

export default function OnboardingGatePage() {
  const t = useTranslations('onboarding.gate')
  const router = useRouter()
  const { status } = useSession()
  const { state, loading, error, reload } = useOnboarding()

  // A dead session must not leave the gate on its loading copy forever
  // (useOnboarding resolves loading=false, error=false, state=null in that
  // case — previously an infinite "Checking your account status...").
  useEffect(() => {
    if (status === 'unauthenticated') {
      router.replace('/login?redirect=/onboarding')
    }
  }, [status, router])

  useEffect(() => {
    if (loading || error || !state) return
    if (!state.consents_current || !state.age_attested) {
      router.replace('/onboarding/consent')
    } else if (state.onboarding_status !== 'company_submitted') {
      router.replace('/onboarding/company')
    } else if (state.approval_status === 'declined') {
      router.replace('/onboarding/declined')
    } else if (state.approval_status !== 'approved') {
      router.replace('/onboarding/pending')
    } else {
      router.replace('/app')
    }
  }, [state, loading, error, router])

  return (
    <div className="text-center py-16">
      {error ? (
        <div className="space-y-4">
          <p className="text-sm" role="alert" style={{ color: '#B3261E' }}>
            {t('error')}
          </p>
          <button
            type="button"
            onClick={() => void reload()}
            className="rounded-lg border px-4 py-2 text-sm"
            style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
          >
            {t('retry')}
          </button>
        </div>
      ) : (
        <p className="text-sm" style={{ color: '#888780' }}>
          {t('loading')}
        </p>
      )}
    </div>
  )
}
