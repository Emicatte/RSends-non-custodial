'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'

const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

export type RemovableMethod = 'password' | 'google' | 'github'

export function ConfirmRemoveModal({
  method,
  onConfirm,
  onClose,
}: {
  method: RemovableMethod
  onConfirm: () => Promise<void>
  onClose: () => void
}) {
  const t = useTranslations('settings.security.signInMethods')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, submitting])

  async function handleConfirm() {
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await onConfirm()
      onClose()
    } catch (err) {
      const code = err instanceof Error ? err.message : 'unknown'
      try {
        setError(t(`errors.${code}`))
      } catch {
        setError(t('errors.unknown'))
      }
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
          {t('confirmRemoveTitle')}
        </h2>
        <p className="text-sm mt-2" style={{ color: INK }}>
          {t('confirmRemoveBody', { method: t(method) })}
        </p>

        {error ? (
          <div
            className="rounded-lg px-3 py-2 text-sm mt-3"
            style={{
              background: 'rgba(192,57,43,0.06)',
              border: `1px solid ${DANGER}`,
              color: INK,
            }}
          >
            {error}
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-2 mt-5">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: 'transparent',
              color: MUTED,
              border: `1px solid ${MUTED}`,
              cursor: submitting ? 'wait' : 'pointer',
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {t('confirmCancel')}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: DANGER,
              color: '#FFFFFF',
              border: 'none',
              cursor: submitting ? 'wait' : 'pointer',
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? t('saving') : t('confirmYes')}
          </button>
        </div>
      </div>
    </div>
  )
}

