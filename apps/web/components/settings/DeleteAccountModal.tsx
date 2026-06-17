'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useAccountSecurity } from '@/hooks/useAccountSecurity'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'
const REQUIRED_PHRASE = 'DELETE MY ACCOUNT'

const KNOWN_ERROR_CODES = new Set<string>([
  'invalid_confirmation',
  'user_not_found',
  'unknown',
  'no_token',
  'session_expired',
])

export function DeleteAccountModal({
  email,
  onClose,
}: {
  email: string
  onClose: () => void
}) {
  const t = useTranslations('settings.security')
  const { requestDeletion } = useAccountSecurity()

  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Esc closes the modal
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, submitting])

  const confirmOk = confirmation.trim() === REQUIRED_PHRASE
  const submitDisabled = !confirmOk || submitting

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
      await requestDeletion({
        reason: reason.trim() || undefined,
        confirmation,
      })
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
          border: `1px solid ${DANGER}`,
          padding: 24,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          className="text-lg font-semibold"
          style={{ color: DANGER, margin: 0 }}
        >
          {t('deleteModal.title')}
        </h2>
        <p className="text-sm mt-2" style={{ color: INK }}>
          {t('deleteModal.body', { email })}
        </p>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: MUTED }}
              htmlFor="deletion-reason"
            >
              {t('deleteModal.reasonLabel')}
            </label>
            <textarea
              id="deletion-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, 500))}
              placeholder={t('deleteModal.reasonPlaceholder')}
              disabled={submitting}
              rows={3}
              className="w-full text-sm rounded-lg px-3 py-2"
              style={{
                color: INK,
                background: '#FFFFFF',
                border: '1px solid rgba(200,81,44,0.25)',
                outline: 'none',
                resize: 'vertical',
              }}
            />
          </div>

          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: MUTED }}
              htmlFor="deletion-confirmation"
            >
              {t('deleteModal.confirmLabel', { phrase: REQUIRED_PHRASE })}
            </label>
            <input
              id="deletion-confirmation"
              type="text"
              autoComplete="off"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              placeholder={t('deleteModal.confirmPlaceholder')}
              disabled={submitting}
              className="w-full text-sm rounded-lg px-3 py-2 font-mono"
              style={{
                color: INK,
                background: '#FFFFFF',
                border: `1px solid ${confirmOk ? DANGER : 'rgba(200,81,44,0.25)'}`,
                outline: 'none',
              }}
            />
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
              {t('deleteModal.cancel')}
            </button>
            <button
              type="submit"
              disabled={submitDisabled}
              className="text-sm px-4 py-2 rounded-lg"
              style={{
                background: DANGER,
                color: '#FFFFFF',
                border: 'none',
                cursor: submitDisabled ? 'not-allowed' : 'pointer',
                opacity: submitDisabled ? 0.5 : 1,
              }}
            >
              {submitting
                ? t('deleteModal.deleting')
                : t('deleteModal.confirmCta')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
