'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useOrganizations, type OrgRole } from '@/hooks/useOrganizations'
import {
  useOrgMembers,
  type InviteItem,
  type MembershipItem,
} from '@/hooks/useOrgMembers'
import { InviteMemberModal } from '@/components/settings/InviteMemberModal'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

export function OrganizationSettings() {
  const t = useTranslations('settings.organization')
  const tErr = useTranslations('settings.organization.errors')
  const { data: session } = useSession()
  const currentUserId = (session as { user?: { id?: string } } | null)?.user?.id ?? null

  const {
    organizations,
    activeOrgId,
    loading: orgsLoading,
    saving: orgSaving,
    error: orgError,
    updateOrganization,
  } = useOrganizations()

  const activeOrg = useMemo(
    () => organizations.find((o) => o.id === activeOrgId) ?? null,
    [organizations, activeOrgId],
  )

  const isAdmin = activeOrg?.role === 'admin'

  const {
    members,
    maxAllowed,
    invites,
    loading: membersLoading,
    saving: membersSaving,
    error: membersError,
    changeRole,
    removeMember,
    revokeInvite,
  } = useOrgMembers(activeOrgId)

  const [showInviteModal, setShowInviteModal] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameSaving, setNameSaving] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)

  useEffect(() => {
    setNameDraft(activeOrg?.name ?? '')
  }, [activeOrg?.id, activeOrg?.name])

  const resolvedError = useMemo(() => {
    const code = orgError ?? membersError
    if (!code) return null
    try {
      return tErr(code)
    } catch {
      return tErr('unknown')
    }
  }, [orgError, membersError, tErr])

  async function commitName() {
    if (!activeOrg) return
    const next = nameDraft.trim().slice(0, 100)
    if (!next || next === activeOrg.name) {
      setEditingName(false)
      setNameDraft(activeOrg.name)
      return
    }
    setNameSaving(true)
    setNameError(null)
    try {
      await updateOrganization(activeOrg.id, { name: next })
      setEditingName(false)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setNameError(code)
    } finally {
      setNameSaving(false)
    }
  }

  if (orgsLoading && !activeOrg) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: MUTED }}>
        {t('loading')}
      </div>
    )
  }

  if (!activeOrg) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: MUTED }}>
        {t('noActiveOrg')}
      </div>
    )
  }

  const membershipsUsed = members.length + invites.length
  const canInviteMore = isAdmin && membershipsUsed < maxAllowed

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
      <header>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: INK, margin: 0 }}>
          {t('title')}
        </h1>
        {activeOrg.is_personal ? (
          <span
            style={{
              display: 'inline-block',
              marginTop: 6,
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 0.6,
              color: ORANGE,
              background: 'rgba(200,81,44,0.08)',
              padding: '2px 8px',
              borderRadius: 999,
              fontWeight: 600,
            }}
          >
            {t('personalBadge')}
          </span>
        ) : null}
      </header>

      {resolvedError ? (
        <div
          role="alert"
          style={{
            padding: '10px 12px',
            background: 'rgba(192,57,43,0.08)',
            borderLeft: `3px solid ${DANGER}`,
            borderRadius: 6,
            fontSize: 13,
            color: DANGER,
          }}
        >
          {resolvedError}
        </div>
      ) : null}

      {/* ─── General ─── */}
      <section>
        <h2
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: INK,
            margin: '0 0 12px',
          }}
        >
          {t('general.title')}
        </h2>
        <div
          style={{
            background: '#FFFFFF',
            border: '1px solid rgba(200,81,44,0.12)',
            borderRadius: 12,
            padding: 20,
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
          }}
        >
          <div>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                color: MUTED,
                marginBottom: 4,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
              }}
            >
              {t('general.name')}
            </label>
            {editingName && isAdmin ? (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="text"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  maxLength={100}
                  autoFocus
                  onBlur={commitName}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      void commitName()
                    } else if (e.key === 'Escape') {
                      setEditingName(false)
                      setNameDraft(activeOrg.name)
                    }
                  }}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    fontSize: 14,
                    border: '1px solid rgba(200,81,44,0.25)',
                    borderRadius: 8,
                    color: INK,
                    outline: 'none',
                  }}
                />
                {nameSaving ? (
                  <span style={{ fontSize: 12, color: MUTED }}>…</span>
                ) : null}
              </div>
            ) : (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontSize: 15, color: INK }}>
                  {activeOrg.name}
                </span>
                {isAdmin && !activeOrg.is_personal ? (
                  <button
                    type="button"
                    onClick={() => setEditingName(true)}
                    style={{
                      fontSize: 12,
                      color: ORANGE,
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                      textDecoration: 'underline',
                    }}
                  >
                    {t('general.editCta')}
                  </button>
                ) : null}
              </div>
            )}
            {nameError ? (
              <div style={{ marginTop: 6, fontSize: 12, color: DANGER }}>
                {nameError}
              </div>
            ) : null}
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                color: MUTED,
                marginBottom: 4,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
              }}
            >
              {t('general.plan')}
            </label>
            <span
              style={{
                display: 'inline-block',
                fontSize: 12,
                padding: '2px 10px',
                border: '1px solid rgba(200,81,44,0.25)',
                borderRadius: 999,
                color: ORANGE,
                background: 'rgba(200,81,44,0.05)',
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                fontWeight: 600,
              }}
            >
              {t('general.freeBadge')}
            </span>
          </div>
        </div>
      </section>

      {/* ─── Members ─── */}
      <section>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            marginBottom: 12,
            flexWrap: 'wrap',
          }}
        >
          <h2 style={{ fontSize: 16, fontWeight: 600, color: INK, margin: 0 }}>
            {t('members.title')}
            <span style={{ marginLeft: 10, fontSize: 12, color: MUTED }}>
              {t('members.count', { current: members.length, max: maxAllowed })}
            </span>
          </h2>
          {isAdmin ? (
            <button
              type="button"
              onClick={() => setShowInviteModal(true)}
              disabled={!canInviteMore}
              title={!canInviteMore ? t('errors.max_members_reached') : ''}
              style={{
                padding: '8px 16px',
                background: ORANGE,
                color: '#FFFFFF',
                border: 'none',
                borderRadius: 10,
                fontSize: 13,
                fontWeight: 500,
                cursor: canInviteMore ? 'pointer' : 'not-allowed',
                opacity: canInviteMore ? 1 : 0.5,
              }}
            >
              {t('invites.sendCta')}
            </button>
          ) : null}
        </div>

        {membersLoading ? (
          <div style={{ padding: 24, color: MUTED, fontSize: 13 }}>
            {t('loading')}
          </div>
        ) : (
          <ul
            style={{
              listStyle: 'none',
              padding: 0,
              margin: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            {members.map((m) => (
              <MemberRow
                key={m.id}
                member={m}
                isAdmin={isAdmin}
                saving={membersSaving}
                isSelf={currentUserId === m.user_id}
                isOwner={activeOrg.owner_user_id === m.user_id}
                onChangeRole={(r) => changeRole(m.user_id, r)}
                onRemove={() => removeMember(m.user_id)}
                t={t}
              />
            ))}
          </ul>
        )}
      </section>

      {/* ─── Invites ─── */}
      <section>
        <h2
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: INK,
            margin: '0 0 12px',
          }}
        >
          {t('invites.title')}
        </h2>
        {invites.length === 0 ? (
          <div
            style={{
              padding: 20,
              background: '#FFFFFF',
              border: '1px dashed rgba(200,81,44,0.2)',
              borderRadius: 12,
              color: MUTED,
              fontSize: 13,
              textAlign: 'center',
            }}
          >
            {t('invites.empty')}
          </div>
        ) : (
          <ul
            style={{
              listStyle: 'none',
              padding: 0,
              margin: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            {invites.map((inv) => (
              <InviteRow
                key={inv.id}
                invite={inv}
                isAdmin={isAdmin}
                saving={membersSaving}
                onRevoke={() => revokeInvite(inv.id)}
                t={t}
              />
            ))}
          </ul>
        )}
      </section>

      {/* ─── Danger zone ─── */}
      {!activeOrg.is_personal && isAdmin ? (
        <section>
          <h2
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: DANGER,
              margin: '0 0 12px',
            }}
          >
            {t('dangerZone.title')}
          </h2>
          <div
            style={{
              background: '#FFFFFF',
              border: `1px solid rgba(192,57,43,0.2)`,
              borderRadius: 12,
              padding: 20,
            }}
          >
            <button
              type="button"
              disabled
              title={t('dangerZone.deleteDisabledHint')}
              style={{
                padding: '10px 16px',
                background: 'transparent',
                color: MUTED,
                border: `1px solid rgba(192,57,43,0.3)`,
                borderRadius: 10,
                fontSize: 13,
                fontWeight: 500,
                cursor: 'not-allowed',
              }}
            >
              {t('dangerZone.deleteOrg')}
            </button>
            <div style={{ marginTop: 8, fontSize: 12, color: MUTED }}>
              {t('dangerZone.deleteDisabledHint')}
            </div>
          </div>
        </section>
      ) : null}

      {showInviteModal ? (
        <InviteMemberModal
          orgId={activeOrg.id}
          onClose={() => setShowInviteModal(false)}
        />
      ) : null}

      {orgSaving ? (
        <div style={{ position: 'fixed', bottom: 16, right: 16, fontSize: 12, color: MUTED }}>
          …
        </div>
      ) : null}
    </div>
  )
}

function MemberRow({
  member,
  isAdmin,
  saving,
  isSelf,
  isOwner,
  onChangeRole,
  onRemove,
  t,
}: {
  member: MembershipItem
  isAdmin: boolean
  saving: boolean
  isSelf: boolean
  isOwner: boolean
  onChangeRole: (r: OrgRole) => Promise<void>
  onRemove: () => Promise<void>
  t: ReturnType<typeof useTranslations>
}) {
  const [confirmRemove, setConfirmRemove] = useState(false)

  useEffect(() => {
    if (!confirmRemove) return
    const timer = setTimeout(() => setConfirmRemove(false), 5000)
    return () => clearTimeout(timer)
  }, [confirmRemove])

  async function handleRoleChange(next: OrgRole) {
    if (next === member.role) return
    try {
      await onChangeRole(next)
    } catch {
      /* surfaced via membersError */
    }
  }

  async function handleRemove() {
    try {
      await onRemove()
    } catch {
      /* surfaced via membersError */
    }
  }

  const roleEditable = isAdmin && !isSelf && !isOwner
  const canRemove = isAdmin && !isSelf && !isOwner

  return (
    <li
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(200,81,44,0.1)',
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: 14,
            color: INK,
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            flexWrap: 'wrap',
          }}
        >
          {member.user_display_name || member.user_email}
          {isSelf ? (
            <span
              style={{
                fontSize: 10,
                textTransform: 'uppercase',
                color: ORANGE,
                background: 'rgba(200,81,44,0.1)',
                padding: '2px 6px',
                borderRadius: 999,
                letterSpacing: 0.5,
              }}
            >
              {t('members.youBadge')}
            </span>
          ) : null}
        </div>
        {member.user_display_name ? (
          <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>
            {member.user_email}
          </div>
        ) : null}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {roleEditable ? (
          <select
            value={member.role}
            onChange={(e) => handleRoleChange(e.target.value as OrgRole)}
            disabled={saving}
            style={{
              padding: '6px 10px',
              fontSize: 13,
              border: '1px solid rgba(200,81,44,0.25)',
              borderRadius: 8,
              color: INK,
              background: '#FFFFFF',
              cursor: saving ? 'wait' : 'pointer',
            }}
          >
            <option value="viewer">{t('members.roleViewer')}</option>
            <option value="operator">{t('members.roleOperator')}</option>
            <option value="admin">{t('members.roleAdmin')}</option>
          </select>
        ) : (
          <span
            style={{
              fontSize: 12,
              padding: '4px 10px',
              background: 'rgba(200,81,44,0.05)',
              color: ORANGE,
              borderRadius: 999,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              fontWeight: 600,
            }}
          >
            {t(`members.role${member.role.charAt(0).toUpperCase() + member.role.slice(1)}`)}
          </span>
        )}

        {canRemove ? (
          confirmRemove ? (
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                onClick={handleRemove}
                disabled={saving}
                style={{
                  padding: '6px 10px',
                  background: DANGER,
                  color: '#FFFFFF',
                  border: 'none',
                  borderRadius: 8,
                  fontSize: 12,
                  cursor: saving ? 'wait' : 'pointer',
                }}
              >
                {t('members.confirmRemove')}
              </button>
              <button
                type="button"
                onClick={() => setConfirmRemove(false)}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  color: MUTED,
                  border: '1px solid rgba(136,135,128,0.3)',
                  borderRadius: 8,
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmRemove(true)}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                color: DANGER,
                border: `1px solid rgba(192,57,43,0.3)`,
                borderRadius: 8,
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {t('members.remove')}
            </button>
          )
        ) : null}
      </div>
    </li>
  )
}

function InviteRow({
  invite,
  isAdmin,
  saving,
  onRevoke,
  t,
}: {
  invite: InviteItem
  isAdmin: boolean
  saving: boolean
  onRevoke: () => Promise<void>
  t: ReturnType<typeof useTranslations>
}) {
  const [confirmRevoke, setConfirmRevoke] = useState(false)

  useEffect(() => {
    if (!confirmRevoke) return
    const timer = setTimeout(() => setConfirmRevoke(false), 5000)
    return () => clearTimeout(timer)
  }, [confirmRevoke])

  async function handleRevoke() {
    try {
      await onRevoke()
    } catch {
      /* surfaced via membersError */
    }
  }

  const expiresDate = new Date(invite.expires_at)
  const expiresLabel = isNaN(expiresDate.getTime())
    ? ''
    : expiresDate.toLocaleDateString()

  return (
    <li
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(200,81,44,0.1)',
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: 14,
            color: INK,
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            flexWrap: 'wrap',
          }}
        >
          {invite.email}
          <span
            style={{
              fontSize: 10,
              textTransform: 'uppercase',
              color: ORANGE,
              background: 'rgba(200,81,44,0.1)',
              padding: '2px 6px',
              borderRadius: 999,
              letterSpacing: 0.5,
            }}
          >
            {t('invites.pendingBadge')}
          </span>
        </div>
        <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>
          {t(`members.role${invite.role.charAt(0).toUpperCase() + invite.role.slice(1)}`)}
          {expiresLabel
            ? ` · ${t('invites.expiresIn', { time: expiresLabel })}`
            : ''}
        </div>
      </div>

      {isAdmin ? (
        confirmRevoke ? (
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={handleRevoke}
              disabled={saving}
              style={{
                padding: '6px 10px',
                background: DANGER,
                color: '#FFFFFF',
                border: 'none',
                borderRadius: 8,
                fontSize: 12,
                cursor: saving ? 'wait' : 'pointer',
              }}
            >
              {t('invites.confirmRevoke')}
            </button>
            <button
              type="button"
              onClick={() => setConfirmRevoke(false)}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                color: MUTED,
                border: '1px solid rgba(136,135,128,0.3)',
                borderRadius: 8,
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              ✕
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmRevoke(true)}
            style={{
              padding: '6px 10px',
              background: 'transparent',
              color: DANGER,
              border: `1px solid rgba(192,57,43,0.3)`,
              borderRadius: 8,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            {t('invites.revoke')}
          </button>
        )
      ) : null}
    </li>
  )
}
