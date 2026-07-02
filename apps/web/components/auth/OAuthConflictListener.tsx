'use client'

import { useEffect, useState } from 'react'
import { AccountLinkingModal, type LinkingScenario } from '@/components/auth/AccountLinkingModal'
import { useEmailAuth } from '@/hooks/useEmailAuth'
import { OAUTH_CONFLICT_EVENT } from '@/lib/oauthExchange'

/**
 * Surfaces the OAuth email-collision (409 email_already_registered) as the
 * AccountLinkingModal — block-and-guide, no auto-linking.
 *
 * Lives INSIDE the locale tree (the modal needs the `auth.linking` i18n
 * context, which AuthBootstrap — mounted in the root layout — doesn't have),
 * and listens for the `rsends:oauth-conflict` event AuthBootstrap dispatches.
 * The scenario is picked via the existing check-email endpoint, the same way
 * SignupForm does; if that lookup fails we fall back to the generic
 * "go to login" variant.
 */
export function OAuthConflictListener() {
  const { checkEmail } = useEmailAuth()
  const [conflict, setConflict] = useState<{
    email: string
    scenario: LinkingScenario
  } | null>(null)

  useEffect(() => {
    const onConflict = (e: Event) => {
      const email = (e as CustomEvent<{ email?: string }>).detail?.email ?? ''
      void (async () => {
        let scenario: LinkingScenario = 'existing-password' // → "go to login"
        if (email) {
          try {
            const methods = await checkEmail(email)
            if (methods.has_password) scenario = 'existing-password'
            else if (methods.has_google) scenario = 'existing-google'
            else if (methods.has_github) scenario = 'existing-github'
          } catch {
            // keep the generic fallback
          }
        }
        setConflict({ email, scenario })
      })()
    }
    window.addEventListener(OAUTH_CONFLICT_EVENT, onConflict)
    return () => window.removeEventListener(OAUTH_CONFLICT_EVENT, onConflict)
  }, [checkEmail])

  if (!conflict) return null
  return (
    <AccountLinkingModal
      scenario={conflict.scenario}
      email={conflict.email}
      onClose={() => setConflict(null)}
    />
  )
}
