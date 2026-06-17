'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import type { OrgRole } from '@/hooks/useOrganizations'
import { useOrgMembers } from '@/hooks/useOrgMembers'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

const KNOWN_ERROR_CODES = new Set<string>([
  'already_member',
  'invite_already_pending',
  'max_members_reached',
  'invalid_role',
  'invalid_email',
  'insufficient_role',
  'not_a_member',
  'not_found',
  'unknown',
])

export function InviteMemberModal({
  orgId,
  onClose,
  onInvited,
}: {
  orgId: string
  onClose: () => void
  onInvited?: () => void
}) {
  const t = useTranslations('settings.organization')
  const { inviteMember } = useOrgMembers(orgId)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('viewer')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (submitting) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, submitting])

  const canSubmit = email.trim().length > 0 && !submitting

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
    if (!canSubmit) return
    setError(null)
    setSubmitting(true)
    try {
      await inviteMember({ email: email.trim().toLowerCase(), role })
      onInvited?.()
      onClose()
    } catch (err) {
      const code = err instanceof Error ? err.message : 'unknown'
      setError(code)
    } finally {
      setSubmitting(false)
    }
  }

  function handleBackdrop() {
    if (submitting) return
    onClose()
  }

  return (
    <div
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(44,44,42,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: 460,
          background: '#FFFFFF',
          borderRadius: 16,
          padding: 28,
          boxShadow: '0 20px 48px rgba(44,44,42,0.2)',
          border: '1px solid rgba(200,81,44,0.15)',
        }}
      >
        <h2
          style={{
            fontSize: 20,
            fontWeight: 700,
            color: INK,
            margin: '0 0 8px',
          }}
        >
          {t('modal.title')}
        </h2>
        <p style={{ fontSize: 13, color: MUTED, margin: '0 0 20px' }}>
          {t('modal.subtitle')}
        </p>

        <form onSubmit={handleSubmit}>
          <label
            style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 500,
              color: INK,
              marginBottom: 6,
            }}
          >
            {t('modal.emailLabel')}
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            autoFocus
            required
            style={{
              width: '100%',
              padding: '10px 12px',
              fontSize: 14,
              border: '1px solid rgba(200,81,44,0.25)',
              borderRadius: 10,
              outline: 'none',
              color: INK,
              marginBottom: 16,
              boxSizing: 'border-box',
            }}
          />

          <label
            style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 500,
              color: INK,
              marginBottom: 6,
            }}
          >
            {t('modal.roleLabel')}
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as OrgRole)}
            style={{
              width: '100%',
              padding: '10px 12px',
              fontSize: 14,
              border: '1px solid rgba(200,81,44,0.25)',
              borderRadius: 10,
              outline: 'none',
              color: INK,
              background: '#FFFFFF',
              marginBottom: 20,
              boxSizing: 'border-box',
            }}
          >
            <option value="viewer">{t('members.roleViewer')}</option>
            <option value="operator">{t('members.roleOperator')}</option>
            <option value="admin">{t('members.roleAdmin')}</option>
          </select>

          {errorMessage ? (
            <div
              style={{
                marginBottom: 16,
                padding: '10px 12px',
                background: 'rgba(192,57,43,0.08)',
                borderLeft: `3px solid ${DANGER}`,
                borderRadius: 6,
                fontSize: 13,
                color: DANGER,
              }}
            >
              {errorMessage}
            </div>
          ) : null}

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              style={{
                padding: '10px 18px',
                background: 'transparent',
                color: MUTED,
                border: '1px solid rgba(136,135,128,0.3)',
                borderRadius: 10,
                fontSize: 14,
                cursor: submitting ? 'not-allowed' : 'pointer',
              }}
            >
              {t('modal.cancel')}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              style={{
                padding: '10px 18px',
                background: ORANGE,
                color: '#FFFFFF',
                border: 'none',
                borderRadius: 10,
                fontSize: 14,
                fontWeight: 500,
                cursor: canSubmit ? 'pointer' : 'not-allowed',
                opacity: canSubmit ? 1 : 0.5,
              }}
            >
              {submitting ? t('modal.sending') : t('modal.sendCta')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
