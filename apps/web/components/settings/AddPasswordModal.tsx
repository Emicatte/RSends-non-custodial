'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  PasswordStrengthMeter,
  scorePassword,
} from '@/components/auth/PasswordStrengthMeter'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

const KNOWN_ERROR_CODES = new Set<string>([
  'password_already_set',
  'password_too_short',
  'password_too_long',
  'password_too_common',
  'password_breached',
  'unknown',
  'no_token',
  'session_expired',
  'user_not_found',
])

export function AddPasswordModal({
  onSubmit,
  onClose,
}: {
  onSubmit: (password: string) => Promise<void>
  onClose: () => void
}) {
  const t = useTranslations('settings.security.signInMethods')

  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, submitting])

  const strong = scorePassword(password) >= 2
  const submitDisabled = !strong || submitting

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (submitDisabled) return
    setError(null)
    setSubmitting(true)
    try {
      await onSubmit(password)
      onClose()
    } catch (err) {
      const code = err instanceof Error ? err.message : 'unknown'
      setError(code)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(44,44,42,0.45)' }}
      onClick={() => {
        if (!submitting) onClose()
      }}
    >
      <div
        className="rounded-2xl w-full max-w-md"
        style={{
          background: '#FFFFFF',
          border: `1px solid ${ORANGE}`,
          padding: 24,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          className="text-lg font-semibold"
          style={{ color: INK, margin: 0 }}
        >
          {t('addPasswordTitle')}
        </h2>
        <p className="text-sm mt-2" style={{ color: MUTED }}>
          {t('addPasswordSubtitle')}
        </p>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: MUTED }}
              htmlFor="add-password-input"
            >
              {t('passwordLabel')}
            </label>
            <input
              id="add-password-input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              className="w-full text-sm rounded-lg px-3 py-2"
              style={{
                color: INK,
                background: '#FFFFFF',
                border: '1px solid rgba(200,81,44,0.25)',
                outline: 'none',
              }}
            />
            <PasswordStrengthMeter password={password} />
          </div>

          {errorMessage ? (
            <div
              className="rounded-lg px-3 py-2 text-sm"
              style={{
                background: 'rgba(192,57,43,0.06)',
                border: `1px solid ${DANGER}`,
                color: INK,
              }}
            >
              {errorMessage}
            </div>
          ) : null}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="text-sm px-4 py-2 rounded-lg"
              style={{
                background: 'transparent',
                color: ORANGE,
                border: `1px solid ${ORANGE}`,
                cursor: submitting ? 'wait' : 'pointer',
                opacity: submitting ? 0.6 : 1,
              }}
            >
              {t('confirmCancel')}
            </button>
            <button
              type="submit"
              disabled={submitDisabled}
              className="text-sm px-4 py-2 rounded-lg"
              style={{
                background: ORANGE,
                color: '#FFFFFF',
                border: 'none',
                cursor: submitDisabled ? 'not-allowed' : 'pointer',
                opacity: submitDisabled ? 0.5 : 1,
              }}
            >
              {submitting ? t('saving') : t('addPasswordCta')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
