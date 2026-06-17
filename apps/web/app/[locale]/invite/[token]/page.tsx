'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSession, signIn } from 'next-auth/react'
import { useParams, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { apiCall } from '@/lib/auth-client'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

interface InvitePreview {
  org_name: string
  role: string
  invite_email: string
  status: string
  email_matches: boolean
  user_email: string
  expires_at: string
}

interface AcceptResponse {
  org_id: string
  role: string
}

type View = 'loading-session' | 'signing-in' | 'loading-preview' | 'preview' | 'done' | 'error'

const KNOWN_ERROR_CODES = new Set<string>([
  'invite_not_found',
  'invite_expired',
  'invite_accepted',
  'invite_declined',
  'invite_revoked',
  'invite_email_mismatch',
  'already_member',
  'max_members_reached',
  'unknown',
])

export default function InvitePage() {
  const params = useParams<{ locale: string; token: string }>()
  const locale = params?.locale ?? 'en'
  const token = params?.token ?? ''
  const router = useRouter()
  const { data: session, status } = useSession()
  const t = useTranslations('invite')

  const [view, setView] = useState<View>('loading-session')
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [confirmDecline, setConfirmDecline] = useState(false)

  const accessToken = (session as { access_token?: string } | null)
    ?.access_token

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  useEffect(() => {
    if (status === 'loading') {
      setView('loading-session')
      return
    }
    if (status === 'unauthenticated') {
      setView('signing-in')
      const callback =
        typeof window !== 'undefined'
          ? window.location.pathname
          : `/${locale}/invite/${token}`
      void signIn('google', { callbackUrl: callback })
      return
    }
    setView('loading-preview')
  }, [status, locale, token])

  useEffect(() => {
    if (view !== 'loading-preview' || !accessToken || !token) return
    let cancelled = false
    void (async () => {
      try {
        const data = await apiCall<InvitePreview>(
          `/api/v1/invites/${token}/preview`,
          accessToken,
        )
        if (cancelled) return
        setPreview(data)
        setView('preview')
      } catch (e) {
        if (cancelled) return
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        setView('error')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [view, accessToken, token])

  const handleAccept = useCallback(async () => {
    if (!accessToken || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await apiCall<AcceptResponse>(`/api/v1/invites/${token}/accept`, accessToken, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      setView('done')
      setTimeout(() => {
        router.push(`/${locale}/settings/organization`)
      }, 1200)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
    } finally {
      setSubmitting(false)
    }
  }, [accessToken, token, router, locale, submitting])

  const handleDecline = useCallback(async () => {
    if (!accessToken || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await apiCall<void>(`/api/v1/invites/${token}/decline`, accessToken, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      setView('done')
      setTimeout(() => {
        router.push(`/${locale}`)
      }, 1200)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
    } finally {
      setSubmitting(false)
    }
  }, [accessToken, token, router, locale, submitting])

  const containerStyle: React.CSSProperties = {
    minHeight: '100vh',
    background: '#FAFAFA',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  }

  const cardStyle: React.CSSProperties = {
    width: '100%',
    maxWidth: 480,
    background: '#FFFFFF',
    border: '1px solid rgba(200,81,44,0.15)',
    borderRadius: 16,
    padding: 40,
    boxShadow: '0 12px 32px rgba(44,44,42,0.08)',
  }

  if (view === 'loading-session' || view === 'signing-in') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          <p style={{ color: MUTED, fontSize: 14, margin: 0, textAlign: 'center' }}>
            {t('loadingPreview')}
          </p>
        </div>
      </div>
    )
  }

  if (view === 'loading-preview') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          <p style={{ color: MUTED, fontSize: 14, margin: 0, textAlign: 'center' }}>
            {t('loadingPreview')}
          </p>
        </div>
      </div>
    )
  }

  if (view === 'error' || !preview) {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: INK, margin: '0 0 16px' }}>
            {t('title')}
          </h1>
          <div
            role="alert"
            style={{
              padding: '12px 14px',
              background: 'rgba(192,57,43,0.08)',
              borderLeft: `3px solid ${DANGER}`,
              borderRadius: 6,
              fontSize: 14,
              color: DANGER,
              margin: 0,
            }}
          >
            {errorMessage ?? t('errors.unknown')}
          </div>
        </div>
      </div>
    )
  }

  if (view === 'done') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: INK, margin: '0 0 12px' }}>
            {t('success')}
          </h1>
          <p style={{ color: MUTED, fontSize: 14, margin: 0 }}>{t('successToMembers')}</p>
        </div>
      </div>
    )
  }

  const expires = new Date(preview.expires_at)
  const expiresLabel = isNaN(expires.getTime()) ? '' : expires.toLocaleString()
  const statusBlocking =
    preview.status !== 'pending'
      ? (`invite_${preview.status}` as const)
      : null

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: INK, margin: '0 0 8px' }}>
          {t('title')}
        </h1>
        <p style={{ color: MUTED, fontSize: 14, margin: '0 0 24px' }}>
          {t('subtitle', {
            org_name: preview.org_name,
            role: preview.role,
          })}
        </p>

        <div
          style={{
            background: 'rgba(200,81,44,0.05)',
            borderLeft: `3px solid ${ORANGE}`,
            borderRadius: 8,
            padding: '14px 18px',
            marginBottom: 20,
            fontSize: 14,
            color: INK,
          }}
        >
          <div style={{ marginBottom: 6 }}>
            <strong style={{ color: INK }}>{t('orgLabel')}:</strong>{' '}
            {preview.org_name}
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong style={{ color: INK }}>{t('roleLabel')}:</strong>{' '}
            {preview.role}
          </div>
          <div>
            <strong style={{ color: INK }}>{t('inviteEmailLabel')}:</strong>{' '}
            {preview.invite_email}
          </div>
          {expiresLabel ? (
            <div style={{ marginTop: 6 }}>
              <strong style={{ color: INK }}>
                {t('expiresAt', { time: expiresLabel })}
              </strong>
            </div>
          ) : null}
        </div>

        {!preview.email_matches ? (
          <div
            role="alert"
            style={{
              padding: '12px 14px',
              background: 'rgba(192,57,43,0.08)',
              borderLeft: `3px solid ${DANGER}`,
              borderRadius: 6,
              fontSize: 13,
              color: DANGER,
              marginBottom: 20,
            }}
          >
            {t('emailMismatchWarning', {
              invite_email: preview.invite_email,
              user_email: preview.user_email,
            })}
          </div>
        ) : null}

        {statusBlocking ? (
          <div
            role="alert"
            style={{
              padding: '12px 14px',
              background: 'rgba(192,57,43,0.08)',
              borderLeft: `3px solid ${DANGER}`,
              borderRadius: 6,
              fontSize: 13,
              color: DANGER,
              marginBottom: 20,
            }}
          >
            {(() => {
              try {
                return t(`errors.${statusBlocking}`)
              } catch {
                return t('errors.unknown')
              }
            })()}
          </div>
        ) : errorMessage ? (
          <div
            role="alert"
            style={{
              padding: '12px 14px',
              background: 'rgba(192,57,43,0.08)',
              borderLeft: `3px solid ${DANGER}`,
              borderRadius: 6,
              fontSize: 13,
              color: DANGER,
              marginBottom: 20,
            }}
          >
            {errorMessage}
          </div>
        ) : null}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          {confirmDecline ? (
            <>
              <button
                type="button"
                onClick={handleDecline}
                disabled={submitting}
                style={{
                  padding: '10px 18px',
                  background: DANGER,
                  color: '#FFFFFF',
                  border: 'none',
                  borderRadius: 10,
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: submitting ? 'wait' : 'pointer',
                }}
              >
                {submitting ? t('declining') : t('declineConfirm')}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDecline(false)}
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
                ✕
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setConfirmDecline(true)}
                disabled={submitting || !!statusBlocking}
                style={{
                  padding: '10px 18px',
                  background: 'transparent',
                  color: MUTED,
                  border: '1px solid rgba(136,135,128,0.3)',
                  borderRadius: 10,
                  fontSize: 14,
                  cursor:
                    submitting || statusBlocking ? 'not-allowed' : 'pointer',
                  opacity: submitting || statusBlocking ? 0.5 : 1,
                }}
              >
                {t('declineCta')}
              </button>
              <button
                type="button"
                onClick={handleAccept}
                disabled={
                  submitting || !preview.email_matches || !!statusBlocking
                }
                style={{
                  padding: '10px 18px',
                  background: ORANGE,
                  color: '#FFFFFF',
                  border: 'none',
                  borderRadius: 10,
                  fontSize: 14,
                  fontWeight: 500,
                  cursor:
                    submitting || !preview.email_matches || statusBlocking
                      ? 'not-allowed'
                      : 'pointer',
                  opacity:
                    submitting || !preview.email_matches || statusBlocking
                      ? 0.5
                      : 1,
                }}
              >
                {submitting ? t('accepting') : t('acceptCta')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
