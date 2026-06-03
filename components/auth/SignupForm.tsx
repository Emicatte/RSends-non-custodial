'use client'

import { useLocale, useTranslations } from 'next-intl'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useEmailAuth, type AccountType, type EmailAuthErrorShape } from '@/hooks/useEmailAuth'
import { PasswordStrengthMeter, scorePassword } from './PasswordStrengthMeter'
import { OAuthDivider } from './OAuthDivider'
import { GoogleSignInButton } from './GoogleSignInButton'
import { GitHubSignInButton } from './GitHubSignInButton'
import { EmailAuthError } from './EmailAuthError'
import { AccountLinkingModal, type LinkingScenario } from './AccountLinkingModal'

const INPUT_STYLE: React.CSSProperties = {
  border: '1px solid rgba(200,81,44,0.25)',
  borderRadius: 10,
  padding: '10px 12px',
  fontSize: 14,
  color: '#2C2C2A',
  background: '#fff',
  width: '100%',
  outline: 'none',
}

export function SignupForm() {
  const t = useTranslations('auth.signup')
  const tCommon = useTranslations('auth')
  const locale = useLocale()
  const router = useRouter()
  const { signup, checkEmail, loading, error, clearError } = useEmailAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [accountType, setAccountType] = useState<AccountType | null>(null)
  const [terms, setTerms] = useState(false)
  const [linking, setLinking] = useState<{
    scenario: LinkingScenario
    email: string
  } | null>(null)
  const checkTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (checkTimer.current) clearTimeout(checkTimer.current)
    }
  }, [])

  const runCheckEmail = useCallback(
    async (value: string) => {
      if (!value || !value.includes('@')) return
      try {
        const r = await checkEmail(value)
        if (r.exists) {
          setLinking({
            scenario: r.has_password
              ? 'existing-password'
              : r.has_github
                ? 'existing-github'
                : 'existing-google',
            email: value,
          })
        }
      } catch {
        // ignore — surface only on submit
      }
    },
    [checkEmail],
  )

  const onEmailBlur = () => {
    if (checkTimer.current) clearTimeout(checkTimer.current)
    const value = email.trim().toLowerCase()
    checkTimer.current = setTimeout(() => runCheckEmail(value), 500)
  }

  const canSubmit =
    email.length > 3 &&
    scorePassword(password) >= 2 &&
    displayName.trim().length >= 1 &&
    accountType !== null &&
    terms &&
    !loading

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    if (!accountType) return
    try {
      await signup({
        email: email.trim().toLowerCase(),
        password,
        display_name: displayName.trim(),
        terms_accepted: terms,
        account_type: accountType,
        locale,
      })
      router.push(
        `/${locale}/verify-email-sent?email=${encodeURIComponent(email.trim().toLowerCase())}`,
      )
    } catch (err) {
      const e = err as EmailAuthErrorShape
      if (e?.code === 'email_already_exists') {
        try {
          const r = await checkEmail(email.trim().toLowerCase())
          setLinking({
            scenario: r.has_password
              ? 'existing-password'
              : r.has_github
                ? 'existing-github'
                : 'existing-google',
            email: email.trim().toLowerCase(),
          })
        } catch {
          // leave error banner
        }
      }
    }
  }

  return (
    <div className="w-full max-w-md">
      <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
        {t('title')}
      </h1>
      <p className="mt-1 text-sm" style={{ color: '#888780' }}>
        {t('subtitle')}
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3">
        <div className="flex flex-col gap-1 text-sm">
          <span style={{ color: '#2C2C2A' }}>{t('accountTypeLabel')}</span>
          <div className="grid grid-cols-2 gap-2">
            {(['individual', 'merchant'] as AccountType[]).map((opt) => {
              const selected = accountType === opt
              return (
                <button
                  key={opt}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setAccountType(opt)}
                  className="rounded-lg px-3 py-2 text-sm font-medium transition-colors"
                  style={{
                    border: selected
                      ? '1px solid #C8512C'
                      : '1px solid rgba(200,81,44,0.25)',
                    background: selected ? 'rgba(200,81,44,0.08)' : '#fff',
                    color: selected ? '#C8512C' : '#2C2C2A',
                  }}
                >
                  {t(opt === 'individual' ? 'accountTypeIndividual' : 'accountTypeMerchant')}
                </button>
              )
            })}
          </div>
        </div>

        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('emailLabel')}
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={onEmailBlur}
            style={INPUT_STYLE}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('passwordLabel')}
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={INPUT_STYLE}
          />
          <PasswordStrengthMeter password={password} />
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('nameLabel')}
          <input
            type="text"
            autoComplete="name"
            required
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            style={INPUT_STYLE}
          />
        </label>

        <label className="flex items-start gap-2 text-sm" style={{ color: '#2C2C2A' }}>
          <input
            type="checkbox"
            checked={terms}
            onChange={(e) => setTerms(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            {t.rich('terms', {
              tos: (chunks) => (
                <Link
                  href={`/${locale}/docs/terms`}
                  style={{ color: '#C8512C', textDecoration: 'underline' }}
                >
                  {chunks}
                </Link>
              ),
              privacy: (chunks) => (
                <Link
                  href={`/${locale}/docs/privacy`}
                  style={{ color: '#C8512C', textDecoration: 'underline' }}
                >
                  {chunks}
                </Link>
              ),
            })}
          </span>
        </label>

        {error ? (
          <EmailAuthError
            code={error.code}
            message={error.message}
            retryAfter={error.retry_after}
          />
        ) : null}

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          style={{ background: '#C8512C', border: 'none' }}
        >
          {loading ? t('submitLoading') : t('submit')}
        </button>
      </form>

      <OAuthDivider />
      <GoogleSignInButton callbackUrl={`/${locale}/app`} disabled={loading} />
      <div className="mt-2">
        <GitHubSignInButton callbackUrl={`/${locale}/app`} disabled={loading} />
      </div>

      <p className="mt-6 text-center text-sm" style={{ color: '#888780' }}>
        {tCommon('haveAccount')}{' '}
        <Link
          href={`/${locale}/login`}
          style={{ color: '#C8512C', textDecoration: 'none' }}
        >
          {tCommon('logIn')}
        </Link>
      </p>

      {linking ? (
        <AccountLinkingModal
          scenario={linking.scenario}
          email={linking.email}
          onClose={() => setLinking(null)}
        />
      ) : null}
    </div>
  )
}
