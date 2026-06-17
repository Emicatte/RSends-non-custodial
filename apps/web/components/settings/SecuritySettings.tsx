'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  useAccountSecurity,
  type ActiveSession,
  type KnownDevice,
} from '@/hooks/useAccountSecurity'
import { DeleteAccountModal } from './DeleteAccountModal'
import { SignInMethodsSection } from './SignInMethodsSection'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

const KNOWN_ERROR_CODES = new Set<string>([
  'account_deleted',
  'invalid_confirmation',
  'cannot_revoke_current_session',
  'not_found',
  'user_not_found',
  'no_token',
  'session_expired',
  'auth_unavailable',
])

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

export function SecuritySettings() {
  const t = useTranslations('settings.security')
  const {
    status,
    sessions,
    devices,
    loading,
    saving,
    error,
    clearError,
    revokeSession,
    revokeAllOthers,
    forgetDevice,
    cancelDeletion,
    reloadAll,
  } = useAccountSecurity()

  const [deleteOpen, setDeleteOpen] = useState(false)

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  const deletionPending = !!status?.deletion_scheduled_for
  const otherSessionsCount = sessions.filter((s) => !s.is_current).length

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1
          className="text-xl font-semibold"
          style={{ color: INK, margin: 0 }}
        >
          {t('title')}
        </h1>
        <p className="text-sm mt-1" style={{ color: MUTED }}>
          {t('subtitle')}
        </p>
      </header>

      {errorMessage ? (
        <div
          className="rounded-lg px-4 py-3 text-sm flex items-start justify-between gap-4"
          style={{
            background: 'rgba(200,81,44,0.06)',
            border: '1px solid rgba(200,81,44,0.2)',
            color: INK,
          }}
        >
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => clearError()}
            className="text-xs"
            style={{
              color: ORANGE,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>
      ) : null}

      {deletionPending && status ? (
        <DeletionPendingBanner
          scheduledFor={status.deletion_scheduled_for}
          daysLeft={status.days_until_deletion}
          saving={saving}
          onCancel={() => {
            void cancelDeletion().catch(() => {})
          }}
          tPending={(k, v) => t(k, v)}
        />
      ) : null}

      {loading ? (
        <p className="text-sm" style={{ color: MUTED }}>
          {t('loading')}
        </p>
      ) : null}

      <SessionsSection
        sessions={sessions}
        saving={saving}
        otherCount={otherSessionsCount}
        onRevoke={(sid) => {
          void revokeSession(sid).catch(() => {})
        }}
        onRevokeAllOthers={() => {
          void revokeAllOthers()
            .then(() => reloadAll())
            .catch(() => {})
        }}
        t={t}
      />

      <DevicesSection
        devices={devices}
        saving={saving}
        onForget={(id) => {
          void forgetDevice(id).catch(() => {})
        }}
        t={t}
      />

      <SignInMethodsSection />

      {!deletionPending ? (
        <DangerZone
          saving={saving}
          onOpen={() => setDeleteOpen(true)}
          t={t}
        />
      ) : null}

      {deleteOpen && status ? (
        <DeleteAccountModal
          email={status.email}
          onClose={() => {
            setDeleteOpen(false)
            void reloadAll()
          }}
        />
      ) : null}
    </div>
  )
}

// ─── Pending-deletion banner (page-local) ──────────────────────────

function DeletionPendingBanner({
  scheduledFor,
  daysLeft,
  saving,
  onCancel,
  tPending,
}: {
  scheduledFor: string | null
  daysLeft: number | null
  saving: boolean
  onCancel: () => void
  tPending: (
    key: string,
    vars?: Record<string, string | number>,
  ) => string
}) {
  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{
        background: 'rgba(192,57,43,0.06)',
        border: `1px solid ${DANGER}`,
      }}
    >
      <div>
        <p
          className="text-sm font-semibold"
          style={{ color: DANGER, margin: 0 }}
        >
          {tPending('deletion.pendingTitle')}
        </p>
        <p className="text-sm mt-1" style={{ color: INK }}>
          {tPending('deletion.pendingBody', {
            days: daysLeft ?? 0,
            date: formatDate(scheduledFor),
          })}
        </p>
      </div>
      <div>
        <button
          type="button"
          disabled={saving}
          onClick={onCancel}
          className="text-sm px-4 py-2 rounded-lg"
          style={{
            background: ORANGE,
            color: '#FFFFFF',
            border: 'none',
            cursor: saving ? 'wait' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          {tPending('deletion.cancel')}
        </button>
      </div>
    </div>
  )
}

// ─── Active sessions ───────────────────────────────────────────────

function SessionsSection({
  sessions,
  saving,
  otherCount,
  onRevoke,
  onRevokeAllOthers,
  t,
}: {
  sessions: ActiveSession[]
  saving: boolean
  otherCount: number
  onRevoke: (sid: string) => void
  onRevokeAllOthers: () => void
  t: ReturnType<typeof useTranslations>
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2
            className="text-base font-semibold"
            style={{ color: INK, margin: 0 }}
          >
            {t('sessions.title')}
          </h2>
          <p className="text-sm mt-1" style={{ color: MUTED }}>
            {t('sessions.description')}
          </p>
        </div>
        {otherCount > 0 ? (
          <button
            type="button"
            disabled={saving}
            onClick={onRevokeAllOthers}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: 'transparent',
              color: ORANGE,
              border: `1px solid ${ORANGE}`,
              cursor: saving ? 'wait' : 'pointer',
              opacity: saving ? 0.6 : 1,
            }}
          >
            {t('sessions.revokeAll')}
          </button>
        ) : null}
      </div>

      {sessions.length === 0 ? (
        <div
          className="rounded-xl p-6 text-center text-sm"
          style={{
            background: 'rgba(200,81,44,0.02)',
            border: '1px dashed rgba(200,81,44,0.2)',
            color: MUTED,
          }}
        >
          {t('sessions.empty')}
        </div>
      ) : (
        <ul className="space-y-2">
          {sessions.map((s) => (
            <li
              key={s.session_id}
              className="rounded-xl p-4 flex items-start justify-between gap-4 flex-wrap"
              style={{
                background: '#FFFFFF',
                border: '1px solid rgba(200,81,44,0.15)',
              }}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-sm font-medium truncate"
                    style={{ color: INK }}
                  >
                    {s.user_agent_snippet ?? '—'}
                  </span>
                  {s.is_current ? (
                    <span
                      className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full"
                      style={{
                        background: 'rgba(200,81,44,0.12)',
                        color: ORANGE,
                      }}
                    >
                      {t('sessions.current')}
                    </span>
                  ) : null}
                </div>
                <p className="text-xs mt-1 font-mono" style={{ color: MUTED }}>
                  {s.ip_address ?? '—'}
                </p>
                <p className="text-xs mt-1" style={{ color: MUTED }}>
                  {t('sessions.lastActivity')}:{' '}
                  {formatDateTime(s.last_activity_at)}
                </p>
              </div>
              <button
                type="button"
                disabled={saving || s.is_current}
                onClick={() => onRevoke(s.session_id)}
                className="text-sm px-3 py-1.5 rounded-lg"
                style={{
                  background: 'transparent',
                  color: s.is_current ? MUTED : DANGER,
                  border: `1px solid ${s.is_current ? MUTED : DANGER}`,
                  cursor: s.is_current
                    ? 'not-allowed'
                    : saving
                      ? 'wait'
                      : 'pointer',
                  opacity: s.is_current ? 0.5 : saving ? 0.6 : 1,
                }}
              >
                {t('sessions.revoke')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ─── Known devices ─────────────────────────────────────────────────

function DevicesSection({
  devices,
  saving,
  onForget,
  t,
}: {
  devices: KnownDevice[]
  saving: boolean
  onForget: (id: string) => void
  t: ReturnType<typeof useTranslations>
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2
          className="text-base font-semibold"
          style={{ color: INK, margin: 0 }}
        >
          {t('devices.title')}
        </h2>
        <p className="text-sm mt-1" style={{ color: MUTED }}>
          {t('devices.description')}
        </p>
      </div>
      {devices.length === 0 ? (
        <div
          className="rounded-xl p-6 text-center text-sm"
          style={{
            background: 'rgba(200,81,44,0.02)',
            border: '1px dashed rgba(200,81,44,0.2)',
            color: MUTED,
          }}
        >
          {t('devices.empty')}
        </div>
      ) : (
        <ul className="space-y-2">
          {devices.map((d) => (
            <li
              key={d.id}
              className="rounded-xl p-4 flex items-start justify-between gap-4 flex-wrap"
              style={{
                background: '#FFFFFF',
                border: '1px solid rgba(200,81,44,0.15)',
              }}
            >
              <div className="flex-1 min-w-0">
                <p
                  className="text-sm font-medium truncate"
                  style={{ color: INK }}
                >
                  {d.user_agent_snippet ?? '—'}
                </p>
                <p className="text-xs mt-1 font-mono" style={{ color: MUTED }}>
                  {d.ip_last_seen ?? '—'}
                </p>
                <p className="text-xs mt-1" style={{ color: MUTED }}>
                  {formatDateTime(d.last_seen_at)} ·{' '}
                  {t('devices.logins', { count: d.login_count })}
                </p>
              </div>
              <button
                type="button"
                disabled={saving}
                onClick={() => onForget(d.id)}
                className="text-sm px-3 py-1.5 rounded-lg"
                style={{
                  background: 'transparent',
                  color: ORANGE,
                  border: `1px solid ${ORANGE}`,
                  cursor: saving ? 'wait' : 'pointer',
                  opacity: saving ? 0.6 : 1,
                }}
              >
                {t('devices.forget')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ─── Danger zone ───────────────────────────────────────────────────

function DangerZone({
  saving,
  onOpen,
  t,
}: {
  saving: boolean
  onOpen: () => void
  t: ReturnType<typeof useTranslations>
}) {
  return (
    <section
      className="rounded-xl p-4 flex items-start justify-between gap-4 flex-wrap"
      style={{
        background: 'rgba(192,57,43,0.04)',
        border: `1px dashed ${DANGER}`,
      }}
    >
      <div className="flex-1 min-w-0">
        <h2
          className="text-base font-semibold"
          style={{ color: DANGER, margin: 0 }}
        >
          {t('danger.title')}
        </h2>
        <p className="text-sm mt-1" style={{ color: INK }}>
          {t('danger.description')}
        </p>
      </div>
      <button
        type="button"
        disabled={saving}
        onClick={onOpen}
        className="text-sm px-4 py-2 rounded-lg"
        style={{
          background: DANGER,
          color: '#FFFFFF',
          border: 'none',
          cursor: saving ? 'wait' : 'pointer',
          opacity: saving ? 0.6 : 1,
        }}
      >
        {t('danger.cta')}
      </button>
    </section>
  )
}
