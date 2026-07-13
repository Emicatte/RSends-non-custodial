'use client'

import { useLocale, useTranslations } from 'next-intl'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useEmailAuth, type AccountType, type EmailAuthErrorShape } from '@/hooks/useEmailAuth'
import { countryOptions } from '@/lib/countries'
import { PasswordStrengthMeter, scorePassword } from './PasswordStrengthMeter'
import { EmailAuthError } from './EmailAuthError'
import { TurnstileWidget } from './TurnstileWidget'
import { AccountLinkingModal } from './AccountLinkingModal'

// Design system: ink #2C2C2A · terracotta #C8512C · paper #FAF8F3/#fff · muted #888780.
const FIELD =
  'w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors ' +
  'bg-white border-[rgba(200,81,44,0.25)] text-[#2C2C2A] ' +
  'focus:border-[#C8512C] focus:ring-2 focus:ring-[rgba(200,81,44,0.15)]'
const LABEL = 'flex flex-col gap-1.5 text-sm font-medium'

const TURNSTILE_ON = !!process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY

export function SignupForm() {
  const t = useTranslations('auth.signup')
  const tCommon = useTranslations('auth')
  const locale = useLocale()
  const router = useRouter()
  const { signup, checkEmail, loading, error, clearError } = useEmailAuth()

  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [dateOfBirth, setDateOfBirth] = useState('')
  const [country, setCountry] = useState('')
  const [accountType, setAccountType] = useState<AccountType | null>(null)
  const [terms, setTerms] = useState(false)
  const [newsletter, setNewsletter] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  const [linking, setLinking] = useState<{ email: string } | null>(null)
  const checkTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (checkTimer.current) clearTimeout(checkTimer.current) }, [])

  // Latest birthdate that is still >= 18 years old today (client-side guard;
  // the server is authoritative and rejects under-18 with 422).
  const maxDob = useMemo(() => {
    const d = new Date()
    d.setFullYear(d.getFullYear() - 18)
    return d.toISOString().slice(0, 10)
  }, [])

  const countries = useMemo(() => countryOptions(locale), [locale])
  const onTurnstile = useCallback((tok: string | null) => setTurnstileToken(tok), [])

  const runCheckEmail = useCallback(
    async (value: string) => {
      if (!value || !value.includes('@')) return
      try {
        const r = await checkEmail(value)
        if (r.exists) {
          setLinking({ email: value })
        }
      } catch {
        /* surface only on submit */
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
    firstName.trim().length >= 1 &&
    lastName.trim().length >= 1 &&
    email.length > 3 &&
    scorePassword(password) >= 2 &&
    !!dateOfBirth &&
    !!country &&
    accountType !== null &&
    terms &&
    (!TURNSTILE_ON || !!turnstileToken) &&
    !loading

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    if (!accountType) return
    const lowerEmail = email.trim().toLowerCase()
    try {
      await signup({
        email: lowerEmail,
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        date_of_birth: dateOfBirth,
        country_of_residence: country,
        account_type: accountType,
        terms_accepted: terms,
        newsletter_opt_in: newsletter,
        turnstile_token: turnstileToken ?? '',
        locale,
      })
      // Email verification no longer gates anything: go straight into the
      // onboarding wizard (consent → company info → approval).
      router.push(`/${locale}/onboarding`)
    } catch (err) {
      const ex = err as EmailAuthErrorShape
      if (ex?.code === 'email_already_exists') {
        setLinking({ email: lowerEmail })
      }
    }
  }

  return (
    <div className="w-full max-w-xl">
      <h1 className="text-2xl font-semibold tracking-tight" style={{ color: '#2C2C2A' }}>
        {t('title')}
      </h1>
      <p className="mt-1 text-sm" style={{ color: '#888780' }}>
        {t('subtitle')}
      </p>

      <form onSubmit={onSubmit} className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* R1 — First name | Surname */}
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('firstNameLabel')}
          <input
            type="text"
            autoComplete="given-name"
            required
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('lastNameLabel')}
          <input
            type="text"
            autoComplete="family-name"
            required
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            className={FIELD}
          />
        </label>

        {/* R2 — Email (full) */}
        <label className={`${LABEL} sm:col-span-2`} style={{ color: '#2C2C2A' }}>
          {t('emailLabel')}
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={onEmailBlur}
            className={FIELD}
          />
        </label>

        {/* R3 — Date of birth | Password */}
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('dobLabel')}
          <input
            type="date"
            autoComplete="bday"
            required
            max={maxDob}
            value={dateOfBirth}
            onChange={(e) => setDateOfBirth(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('passwordLabel')}
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={FIELD}
          />
          <PasswordStrengthMeter password={password} />
        </label>

        {/* R4 — Country/Region (full) */}
        <label className={`${LABEL} sm:col-span-2`} style={{ color: '#2C2C2A' }}>
          {t('countryLabel')}
          <select
            required
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className={FIELD}
            style={{ color: country ? '#2C2C2A' : '#888780' }}
          >
            <option value="" disabled>
              {t('countryPlaceholder')}
            </option>
            {countries.map((c) => (
              <option key={c.code} value={c.code} style={{ color: '#2C2C2A' }}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        {/* R5 — Account type (full) */}
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <span className="text-sm font-medium" style={{ color: '#2C2C2A' }}>
            {t('accountTypeLabel')}
          </span>
          <div className="grid grid-cols-2 gap-2">
            {(['individual', 'merchant'] as AccountType[]).map((opt) => {
              const selected = accountType === opt
              return (
                <button
                  key={opt}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setAccountType(opt)}
                  className="rounded-lg px-3 py-2.5 text-sm font-medium transition-colors"
                  style={{
                    border: selected ? '1px solid #C8512C' : '1px solid rgba(200,81,44,0.25)',
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

        {/* R6 — ToS (required) + Newsletter (optional) */}
        <div className="flex flex-col gap-2 sm:col-span-2">
          <label className="flex items-start gap-2 text-sm" style={{ color: '#2C2C2A' }}>
            <input
              type="checkbox"
              checked={terms}
              onChange={(e) => setTerms(e.target.checked)}
              className="mt-0.5 accent-[#C8512C]"
            />
            <span>
              {t.rich('terms', {
                tos: (chunks) => (
                  <Link href={`/${locale}/docs/terms`} style={{ color: '#C8512C', textDecoration: 'underline' }}>
                    {chunks}
                  </Link>
                ),
                privacy: (chunks) => (
                  <Link href={`/${locale}/docs/privacy`} style={{ color: '#C8512C', textDecoration: 'underline' }}>
                    {chunks}
                  </Link>
                ),
              })}
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm" style={{ color: '#888780' }}>
            <input
              type="checkbox"
              checked={newsletter}
              onChange={(e) => setNewsletter(e.target.checked)}
              className="mt-0.5 accent-[#C8512C]"
            />
            <span>{t('newsletterLabel')}</span>
          </label>
        </div>

        {/* R7 — Turnstile */}
        {TURNSTILE_ON ? (
          <div className="sm:col-span-2">
            <TurnstileWidget onToken={onTurnstile} />
          </div>
        ) : null}

        {error ? (
          <div className="sm:col-span-2">
            <EmailAuthError code={error.code} message={error.message} retryAfter={error.retry_after} />
          </div>
        ) : null}

        {/* R8 — Create account */}
        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-2"
          style={{ background: '#C8512C', border: 'none' }}
        >
          {loading ? t('submitLoading') : t('submit')}
        </button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: '#888780' }}>
        {tCommon('haveAccount')}{' '}
        <Link href={`/${locale}/login`} style={{ color: '#C8512C', textDecoration: 'none' }}>
          {tCommon('logIn')}
        </Link>
      </p>

      {linking ? (
        <AccountLinkingModal
          email={linking.email}
          onClose={() => setLinking(null)}
        />
      ) : null}
    </div>
  )
}
