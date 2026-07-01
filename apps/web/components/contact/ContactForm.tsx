'use client'

import { useTranslations } from 'next-intl'
import { useCallback, useState } from 'react'
import { TurnstileWidget } from '@/components/auth/TurnstileWidget'

// Design system: ink #2C2C2A · terracotta #C8512C · paper/#fff · muted #888780.
const FIELD =
  'w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors ' +
  'bg-white border-[rgba(200,81,44,0.25)] text-[#2C2C2A] ' +
  'focus:border-[#C8512C] focus:ring-2 focus:ring-[rgba(200,81,44,0.15)]'
const LABEL = 'flex flex-col gap-1.5 text-sm font-medium'

const TURNSTILE_ON = !!process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY

// Server error envelope codes → translation keys under `contact.errors`.
const ERROR_KEYS: Record<string, string> = {
  INVALID_REQUEST: 'invalidRequest',
  VALIDATION_FAILED: 'validation',
  RATE_LIMIT_EXCEEDED: 'rateLimit',
  TURNSTILE_FAILED: 'turnstile',
  TURNSTILE_UNCONFIGURED: 'turnstile',
  EMAIL_SEND_FAILED: 'sendFailed',
}

export function ContactForm() {
  const t = useTranslations('contact')

  const [name, setName] = useState('')
  const [surname, setSurname] = useState('')
  const [company, setCompany] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [honeypot, setHoneypot] = useState('')
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [errorKey, setErrorKey] = useState<string | null>(null)

  const onTurnstile = useCallback((tok: string | null) => setTurnstileToken(tok), [])

  const canSubmit =
    name.trim().length >= 1 &&
    surname.trim().length >= 1 &&
    email.trim().length > 3 &&
    message.trim().length >= 1 &&
    (!TURNSTILE_ON || !!turnstileToken) &&
    !loading

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorKey(null)
    setLoading(true)
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          surname: surname.trim(),
          company: company.trim(),
          email: email.trim(),
          message: message.trim(),
          company_website: honeypot,
          turnstile_token: turnstileToken ?? '',
        }),
      })
      if (res.ok) {
        setSent(true)
        return
      }
      const data = (await res.json().catch(() => ({}))) as { error?: string }
      setErrorKey(ERROR_KEYS[data.error ?? ''] ?? 'network')
    } catch {
      setErrorKey('network')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="w-full max-w-xl">
        <h1 className="text-2xl font-semibold tracking-tight" style={{ color: '#2C2C2A' }}>
          {t('successTitle')}
        </h1>
        <p className="mt-2 text-sm" style={{ color: '#888780' }}>
          {t('successBody')}
        </p>
      </div>
    )
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
        {/* Name | Surname */}
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('nameLabel')}
          <input
            type="text"
            autoComplete="given-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={LABEL} style={{ color: '#2C2C2A' }}>
          {t('surnameLabel')}
          <input
            type="text"
            autoComplete="family-name"
            required
            maxLength={100}
            value={surname}
            onChange={(e) => setSurname(e.target.value)}
            className={FIELD}
          />
        </label>

        {/* Company (optional, full) */}
        <label className={`${LABEL} sm:col-span-2`} style={{ color: '#2C2C2A' }}>
          {t('companyLabel')}
          <input
            type="text"
            autoComplete="organization"
            maxLength={100}
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className={FIELD}
          />
        </label>

        {/* Email (full) */}
        <label className={`${LABEL} sm:col-span-2`} style={{ color: '#2C2C2A' }}>
          {t('emailLabel')}
          <input
            type="email"
            autoComplete="email"
            required
            maxLength={200}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={FIELD}
          />
        </label>

        {/* Message (full) */}
        <label className={`${LABEL} sm:col-span-2`} style={{ color: '#2C2C2A' }}>
          {t('messageLabel')}
          <textarea
            required
            maxLength={5000}
            rows={6}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className={`${FIELD} resize-y`}
          />
        </label>

        {/* Honeypot — hidden from real users, visible to naive bots. */}
        <input
          type="text"
          name="company_website"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          value={honeypot}
          onChange={(e) => setHoneypot(e.target.value)}
          style={{ position: 'absolute', left: '-9999px', width: 1, height: 1, opacity: 0 }}
        />

        {/* Turnstile */}
        {TURNSTILE_ON ? (
          <div className="sm:col-span-2">
            <TurnstileWidget onToken={onTurnstile} />
          </div>
        ) : null}

        {errorKey ? (
          <div
            className="sm:col-span-2 rounded-lg px-3 py-2.5 text-sm"
            role="alert"
            style={{ background: 'rgba(200,81,44,0.08)', color: '#C8512C', border: '1px solid rgba(200,81,44,0.25)' }}
          >
            {t(`errors.${errorKey}`)}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-2"
          style={{ background: '#C8512C', border: 'none' }}
        >
          {loading ? t('submitLoading') : t('submit')}
        </button>
      </form>
    </div>
  )
}
