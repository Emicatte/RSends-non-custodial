'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations, useLocale } from 'next-intl'
import { useUserApiKeys, type ApiKeyListItem } from '@/hooks/useUserApiKeys'
import { CreateApiKeyModal } from './CreateApiKeyModal'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'
const TEAM_BANNER_BG = 'rgba(200,81,44,0.06)'

const KNOWN_ERROR_CODES = new Set<string>([
  'max_keys_reached',
  'not_found',
  'unknown',
  'no_token',
  'session_expired',
  'auth_unavailable',
  'insufficient_role',
  'no_active_org',
  'not_a_member',
])

export function ApiKeysSettings() {
  const t = useTranslations('settings.apiKeys')
  const locale = useLocale()
  const { data: session } = useSession()
  const currentUserId =
    (session as { user?: { id?: string } } | null)?.user?.id ?? null
  const {
    keys,
    maxAllowed,
    remainingSlots,
    loading,
    saving,
    error,
    isAuthed,
    activeOrg,
    currentUserRole,
    reload,
    updateLabel,
    revokeKey,
    clearError,
  } = useUserApiKeys()

  const [modalOpen, setModalOpen] = useState(false)

  const usedCount = maxAllowed - remainingSlots
  const limitReached = remainingSlots === 0

  // Prompt 11 — RBAC gates. Operators can create/edit labels; only admins can
  // revoke. Viewers see everything but can't mutate. Buttons stay visible but
  // disabled (with tooltip) to make the role constraint discoverable.
  const canCreate =
    currentUserRole === 'admin' || currentUserRole === 'operator'
  const canEditLabel = canCreate
  const canRevoke = currentUserRole === 'admin'
  const isTeamOrg = !!activeOrg && !activeOrg.is_personal
  const viewerHint = t('viewerDisabledHint')
  const adminOnlyHint = t('adminOnlyHint')

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  if (!isAuthed) {
    return (
      <div style={{ color: MUTED, padding: 16 }}>{t('loading')}</div>
    )
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <header>
        <h1 className="text-2xl font-semibold" style={{ color: INK, margin: 0 }}>
          {t('title')}
        </h1>
        <p className="text-sm mt-2" style={{ color: MUTED }}>
          {t('description')}
        </p>
        <p className="text-xs mt-2" style={{ color: MUTED }}>
          {t('countUsed', { used: usedCount, max: maxAllowed })}
        </p>
      </header>

      {isTeamOrg ? (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{
            background: TEAM_BANNER_BG,
            border: `1px solid rgba(200,81,44,0.2)`,
            color: INK,
          }}
        >
          {t('teamBanner', { orgName: activeOrg?.name ?? '' })}
        </div>
      ) : null}

      {errorMessage ? (
        <div
          className="rounded-lg px-3 py-2 text-sm flex items-center justify-between gap-3"
          style={{
            background: 'rgba(192,57,43,0.06)',
            border: `1px solid ${DANGER}`,
            color: INK,
          }}
        >
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={clearError}
            className="text-xs"
            style={{
              background: 'transparent',
              color: MUTED,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <div style={{ color: MUTED, fontSize: 12 }}>
          {limitReached ? t('limitReached', { max: maxAllowed }) : ''}
        </div>
        <button
          type="button"
          disabled={limitReached || loading || !canCreate}
          onClick={() => setModalOpen(true)}
          title={
            !canCreate
              ? viewerHint
              : limitReached
                ? t('limitReached', { max: maxAllowed })
                : undefined
          }
          className="text-sm px-4 py-2 rounded-lg"
          style={{
            background: ORANGE,
            color: '#FFFFFF',
            border: 'none',
            cursor:
              limitReached || loading || !canCreate
                ? 'not-allowed'
                : 'pointer',
            opacity: limitReached || loading || !canCreate ? 0.5 : 1,
          }}
        >
          {t('createCta')}
        </button>
      </div>

      {loading && keys.length === 0 ? (
        <div style={{ color: MUTED }}>{t('loading')}</div>
      ) : keys.length === 0 ? (
        <div
          className="rounded-xl p-6 text-center"
          style={{
            background: '#FFFFFF',
            border: '1px solid rgba(200,81,44,0.1)',
          }}
        >
          <p className="text-sm" style={{ color: INK, margin: 0 }}>
            {t('empty.title')}
          </p>
          <button
            type="button"
            disabled={limitReached || !canCreate}
            onClick={() => setModalOpen(true)}
            title={!canCreate ? viewerHint : undefined}
            className="text-sm mt-3 px-4 py-2 rounded-lg"
            style={{
              background: ORANGE,
              color: '#FFFFFF',
              border: 'none',
              cursor: limitReached || !canCreate ? 'not-allowed' : 'pointer',
              opacity: limitReached || !canCreate ? 0.5 : 1,
            }}
          >
            {t('empty.cta')}
          </button>
        </div>
      ) : (
        <ul className="flex flex-col gap-3 list-none p-0 m-0">
          {keys.map((k) => (
            <ApiKeyRow
              key={k.id}
              apiKey={k}
              saving={saving}
              locale={locale}
              canEditLabel={canEditLabel}
              canRevoke={canRevoke}
              viewerHint={viewerHint}
              adminOnlyHint={adminOnlyHint}
              currentUserId={currentUserId}
              onUpdateLabel={(label) => updateLabel(k.id, label)}
              onRevoke={() => revokeKey(k.id)}
              t={t}
            />
          ))}
        </ul>
      )}

      <DocsSnippet t={t} />

      {modalOpen ? (
        <CreateApiKeyModal
          onClose={() => setModalOpen(false)}
          onCreated={() => void reload()}
        />
      ) : null}
    </div>
  )
}

function ApiKeyRow({
  apiKey,
  saving,
  locale,
  canEditLabel,
  canRevoke,
  viewerHint,
  adminOnlyHint,
  currentUserId,
  onUpdateLabel,
  onRevoke,
  t,
}: {
  apiKey: ApiKeyListItem
  saving: boolean
  locale: string
  canEditLabel: boolean
  canRevoke: boolean
  viewerHint: string
  adminOnlyHint: string
  currentUserId: string | null
  onUpdateLabel: (label: string) => Promise<void>
  onRevoke: () => Promise<void>
  t: ReturnType<typeof useTranslations>
}) {
  const [editingLabel, setEditingLabel] = useState(false)
  const [labelDraft, setLabelDraft] = useState(apiKey.label)
  const [confirmRevoke, setConfirmRevoke] = useState(false)

  const createdByOther =
    !!apiKey.created_by_user_id &&
    !!currentUserId &&
    apiKey.created_by_user_id !== currentUserId
  const createdByLabel = apiKey.created_by_email ?? ''

  useEffect(() => {
    setLabelDraft(apiKey.label)
  }, [apiKey.label])

  useEffect(() => {
    if (!confirmRevoke) return
    const to = setTimeout(() => setConfirmRevoke(false), 5000)
    return () => clearTimeout(to)
  }, [confirmRevoke])

  async function commitLabel() {
    const next = labelDraft.trim().slice(0, 100)
    setEditingLabel(false)
    if (next === apiKey.label) return
    if (next.length === 0) return
    await onUpdateLabel(next)
  }

  const revoked = !apiKey.is_active || apiKey.revoked_at !== null
  const lastUsed = apiKey.last_used_at
    ? formatDateTime(apiKey.last_used_at, locale)
    : t('never')

  return (
    <li
      className="rounded-xl p-4"
      style={{
        background: '#FFFFFF',
        border: `1px solid ${revoked ? 'rgba(136,135,128,0.2)' : 'rgba(200,81,44,0.1)'}`,
        opacity: revoked ? 0.75 : 1,
      }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {editingLabel && !revoked && canEditLabel ? (
              <input
                type="text"
                value={labelDraft}
                autoFocus
                maxLength={100}
                onChange={(e) => setLabelDraft(e.target.value)}
                onBlur={() => void commitLabel()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void commitLabel()
                  } else if (e.key === 'Escape') {
                    setLabelDraft(apiKey.label)
                    setEditingLabel(false)
                  }
                }}
                className="text-sm px-2 py-1 rounded"
                style={{
                  border: '1px solid rgba(200,81,44,0.3)',
                  color: INK,
                  background: '#FAFAFA',
                  minWidth: 200,
                }}
              />
            ) : (
              <button
                type="button"
                onClick={() =>
                  !revoked && canEditLabel && setEditingLabel(true)
                }
                disabled={revoked || !canEditLabel}
                title={!canEditLabel && !revoked ? viewerHint : undefined}
                className="text-sm font-semibold"
                style={{
                  color: INK,
                  background: 'transparent',
                  border: 'none',
                  padding: 0,
                  cursor: revoked || !canEditLabel ? 'default' : 'pointer',
                  textAlign: 'left',
                }}
              >
                {apiKey.label}
              </button>
            )}
            <span
              className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded"
              style={{
                background: revoked ? MUTED : ORANGE,
                color: '#FFFFFF',
              }}
            >
              {revoked ? t('statusRevoked') : t('statusActive')}
            </span>
          </div>

          <div className="mt-2">
            <span
              className="text-xs font-mono"
              style={{ color: MUTED }}
            >
              {apiKey.display_prefix}
            </span>
          </div>

          <div className="mt-2 flex items-center gap-1 flex-wrap">
            {apiKey.scopes.map((s) => (
              <span
                key={s}
                className="text-[10px] font-mono px-2 py-0.5 rounded"
                style={{
                  background: 'rgba(200,81,44,0.08)',
                  color: ORANGE,
                }}
              >
                {s}
              </span>
            ))}
          </div>

          <div
            className="mt-2 flex items-center gap-3 flex-wrap"
            style={{ fontSize: 11, color: MUTED }}
          >
            <span>{t('rateLimit', { rpm: apiKey.rate_limit_rpm })}</span>
            <span>•</span>
            <span>{t('totalRequests', { count: apiKey.total_requests })}</span>
            <span>•</span>
            <span>{t('lastUsed', { time: lastUsed })}</span>
          </div>

          {createdByOther && createdByLabel ? (
            <div
              className="mt-1"
              style={{ fontSize: 11, color: MUTED, fontStyle: 'italic' }}
            >
              {t('addedBy', { email: createdByLabel })}
            </div>
          ) : null}
        </div>

        {!revoked ? (
          <div className="flex items-center gap-2 flex-shrink-0">
            {confirmRevoke && canRevoke ? (
              <>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    setConfirmRevoke(false)
                    void onRevoke()
                  }}
                  className="text-xs px-3 py-1.5 rounded-lg"
                  style={{
                    background: DANGER,
                    color: '#FFFFFF',
                    border: 'none',
                    cursor: saving ? 'wait' : 'pointer',
                    opacity: saving ? 0.6 : 1,
                  }}
                >
                  {t('confirmRevoke')}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmRevoke(false)}
                  className="text-xs px-3 py-1.5 rounded-lg"
                  style={{
                    background: 'transparent',
                    color: MUTED,
                    border: '1px solid rgba(136,135,128,0.3)',
                    cursor: 'pointer',
                  }}
                >
                  {t('cancel')}
                </button>
              </>
            ) : (
              <button
                type="button"
                disabled={saving || !canRevoke}
                onClick={() => canRevoke && setConfirmRevoke(true)}
                title={!canRevoke ? adminOnlyHint : undefined}
                className="text-xs px-3 py-1.5 rounded-lg"
                style={{
                  background: 'transparent',
                  color: DANGER,
                  border: `1px solid ${DANGER}`,
                  cursor: saving || !canRevoke ? 'not-allowed' : 'pointer',
                  opacity: saving || !canRevoke ? 0.5 : 1,
                }}
              >
                {t('revoke')}
              </button>
            )}
          </div>
        ) : null}
      </div>
    </li>
  )
}

function DocsSnippet({ t }: { t: ReturnType<typeof useTranslations> }) {
  return (
    <section
      className="rounded-xl p-4"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(200,81,44,0.1)',
      }}
    >
      <h2
        className="text-sm font-semibold"
        style={{ color: INK, margin: 0 }}
      >
        {t('docs.title')}
      </h2>
      <p className="text-xs mt-2" style={{ color: MUTED, margin: 0 }}>
        {t('docs.body')}
      </p>
      <pre
        className="text-xs font-mono rounded-lg px-3 py-3 mt-3 whitespace-pre-wrap break-all"
        style={{
          color: INK,
          background: 'rgba(44,44,42,0.04)',
          border: '1px solid rgba(136,135,128,0.25)',
          margin: 0,
        }}
      >{`curl https://api.rsends.io/api/v1/user/transactions \\
  -H "Authorization: Bearer rsusr_live_..."`}</pre>
    </section>
  )
}

function formatDateTime(iso: string, locale: string): string {
  try {
    const d = new Date(iso)
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(d)
  } catch {
    return iso
  }
}
