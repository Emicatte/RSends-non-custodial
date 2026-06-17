'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useAccount, useChainId, useSignMessage } from 'wagmi'
import { useConnectModal } from '@rainbow-me/rainbowkit'
import { useUserWallets, type UserWallet } from '@/hooks/useUserWallets'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const TEAM_BANNER_BG = 'rgba(200,81,44,0.06)'

const KNOWN_ERROR_CODES = new Set<string>([
  'wallet_already_linked',
  'max_wallets_reached',
  'chain_not_supported',
  'chain_family_unsupported_v1',
  'nonce_expired_or_used',
  'nonce_context_mismatch',
  'signature_mismatch',
  'signature_malformed',
  'invalid_address',
  'cannot_demote_primary',
  'siwe_unavailable',
  'not_found',
  'primary_race',
  'insufficient_role',
  'no_active_org',
  'not_a_member',
])

function truncateAddr(addr: string): string {
  if (!addr || addr.length < 12) return addr
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

export function WalletsSettings() {
  const t = useTranslations('settings.wallets')
  const { data: session } = useSession()
  const currentUserId =
    (session as { user?: { id?: string } } | null)?.user?.id ?? null
  const {
    wallets,
    maxAllowed,
    remainingSlots,
    loading,
    saving,
    error,
    activeOrg,
    currentUserRole,
    requestChallenge,
    verifyAndLink,
    setPrimary,
    updateLabel,
    unlink,
    clearError,
  } = useUserWallets()

  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { signMessageAsync } = useSignMessage()
  const { openConnectModal } = useConnectModal()

  const [linking, setLinking] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  // Prompt 11 — RBAC gates. Operators can link wallets and edit labels.
  // Only admins can set primary or unlink (shared-team-resource safety).
  const canLink =
    currentUserRole === 'admin' || currentUserRole === 'operator'
  const canEditLabel = canLink
  const canSetPrimary = currentUserRole === 'admin'
  const canUnlink = currentUserRole === 'admin'
  const isTeamOrg = !!activeOrg && !activeOrg.is_personal
  const viewerHint = t('viewerDisabledHint')
  const adminOnlyHint = t('adminOnlyHint')

  const effectiveError = localError ?? error
  const errorMessage = useMemo(() => {
    if (!effectiveError) return null
    const code = KNOWN_ERROR_CODES.has(effectiveError)
      ? effectiveError
      : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [effectiveError, t])

  const connectedAddressLower = address?.toLowerCase()
  const alreadyLinked = useMemo(
    () =>
      !!connectedAddressLower &&
      wallets.some((w) => w.address === connectedAddressLower),
    [connectedAddressLower, wallets],
  )

  const showAutoSuggest =
    isConnected &&
    !alreadyLinked &&
    !!address &&
    wallets.length > 0 &&
    remainingSlots > 0 &&
    canLink

  const showEmptyState = !loading && wallets.length === 0

  async function handleLink(targetAddress?: string) {
    setLocalError(null)
    clearError()
    const addr = targetAddress ?? address
    if (!addr) {
      if (openConnectModal) openConnectModal()
      return
    }
    if (!chainId) {
      setLocalError('chain_not_supported')
      return
    }
    setLinking(true)
    try {
      const challenge = await requestChallenge(addr, chainId)
      const signature = await signMessageAsync({
        message: challenge.siwe_message,
      })
      await verifyAndLink({
        address: addr,
        chainId,
        nonce: challenge.nonce,
        signature,
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'unknown'
      if (msg === 'UserRejectedRequestError' || /reject/i.test(msg)) {
        // user cancelled — silent
      } else {
        setLocalError(msg)
      }
    } finally {
      setLinking(false)
    }
  }

  if (loading && wallets.length === 0) {
    return (
      <div className="text-sm" style={{ color: MUTED }}>
        {t('loading')}
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <section>
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <h2
              className="text-xl font-semibold mb-1"
              style={{ color: INK }}
            >
              {t('title')}
            </h2>
            <p className="text-sm" style={{ color: MUTED }}>
              {t('subtitle')}
            </p>
          </div>
          <div className="text-xs" style={{ color: MUTED }}>
            {t('countUsed', {
              used: wallets.length,
              max: maxAllowed,
            })}
          </div>
        </div>
      </section>

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
          role="alert"
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
            onClick={() => {
              setLocalError(null)
              clearError()
            }}
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

      {showAutoSuggest ? (
        <div
          className="rounded-xl p-4 flex items-center justify-between gap-4 flex-wrap"
          style={{
            background: 'rgba(200,81,44,0.04)',
            border: '1px dashed rgba(200,81,44,0.25)',
          }}
        >
          <div>
            <p
              className="text-sm font-medium mb-1"
              style={{ color: INK }}
            >
              {t('autoSuggest.title')}
            </p>
            <p className="text-xs font-mono" style={{ color: MUTED }}>
              {truncateAddr(address!)}
            </p>
          </div>
          <button
            type="button"
            disabled={linking || saving}
            onClick={() => handleLink()}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: ORANGE,
              color: '#FFFFFF',
              border: 'none',
              cursor: linking || saving ? 'wait' : 'pointer',
              opacity: linking || saving ? 0.6 : 1,
            }}
          >
            {linking ? t('linking') : t('autoSuggest.cta')}
          </button>
        </div>
      ) : null}

      {showEmptyState ? (
        <div
          className="rounded-xl p-8 text-center"
          style={{
            background: 'rgba(200,81,44,0.02)',
            border: '1px dashed rgba(200,81,44,0.2)',
          }}
        >
          <p
            className="text-sm font-medium mb-2"
            style={{ color: INK }}
          >
            {t('empty.title')}
          </p>
          <button
            type="button"
            disabled={linking || saving || !canLink}
            onClick={() => handleLink()}
            title={!canLink ? viewerHint : undefined}
            className="text-sm px-4 py-2 rounded-lg mt-2"
            style={{
              background: ORANGE,
              color: '#FFFFFF',
              border: 'none',
              cursor:
                linking || saving || !canLink ? 'not-allowed' : 'pointer',
              opacity: linking || saving || !canLink ? 0.6 : 1,
            }}
          >
            {linking ? t('linking') : t('empty.cta')}
          </button>
        </div>
      ) : null}

      {wallets.length > 0 ? (
        <ul className="space-y-2">
          {wallets.map((w) => (
            <WalletRow
              key={w.id}
              wallet={w}
              saving={saving}
              canEditLabel={canEditLabel}
              canSetPrimary={canSetPrimary}
              canUnlink={canUnlink}
              viewerHint={viewerHint}
              adminOnlyHint={adminOnlyHint}
              currentUserId={currentUserId}
              onSetPrimary={() => {
                setLocalError(null)
                clearError()
                void setPrimary(w.id).catch(() => {})
              }}
              onUpdateLabel={(label) => {
                setLocalError(null)
                clearError()
                return updateLabel(w.id, label).catch(() => {})
              }}
              onUnlink={() => {
                setLocalError(null)
                clearError()
                return unlink(w.id).catch(() => {})
              }}
              t={t}
            />
          ))}
        </ul>
      ) : null}

      {wallets.length > 0 && remainingSlots > 0 ? (
        <div>
          <button
            type="button"
            disabled={linking || saving || !canLink}
            onClick={() => {
              if (!canLink) return
              if (!isConnected && openConnectModal) {
                openConnectModal()
                return
              }
              void handleLink()
            }}
            title={!canLink ? viewerHint : undefined}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: 'transparent',
              color: ORANGE,
              border: `1px solid ${ORANGE}`,
              cursor:
                linking || saving || !canLink ? 'not-allowed' : 'pointer',
              opacity: linking || saving || !canLink ? 0.6 : 1,
            }}
          >
            {linking ? t('linking') : t('linkAnother')}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function WalletRow({
  wallet,
  saving,
  canEditLabel,
  canSetPrimary,
  canUnlink,
  viewerHint,
  adminOnlyHint,
  currentUserId,
  onSetPrimary,
  onUpdateLabel,
  onUnlink,
  t,
}: {
  wallet: UserWallet
  saving: boolean
  canEditLabel: boolean
  canSetPrimary: boolean
  canUnlink: boolean
  viewerHint: string
  adminOnlyHint: string
  currentUserId: string | null
  onSetPrimary: () => void
  onUpdateLabel: (label: string) => Promise<void>
  onUnlink: () => Promise<void>
  t: ReturnType<typeof useTranslations>
}) {
  const [editingLabel, setEditingLabel] = useState(false)
  const [labelDraft, setLabelDraft] = useState(wallet.label)
  const [confirmUnlink, setConfirmUnlink] = useState(false)

  const createdByOther =
    !!wallet.created_by_user_id &&
    !!currentUserId &&
    wallet.created_by_user_id !== currentUserId
  const createdByLabel = wallet.created_by_email ?? ''

  useEffect(() => {
    setLabelDraft(wallet.label)
  }, [wallet.label])

  useEffect(() => {
    if (!confirmUnlink) return
    const t = setTimeout(() => setConfirmUnlink(false), 5000)
    return () => clearTimeout(t)
  }, [confirmUnlink])

  async function commitLabel() {
    const next = labelDraft.trim().slice(0, 64)
    setEditingLabel(false)
    if (next === wallet.label) return
    await onUpdateLabel(next)
  }

  return (
    <li
      className="rounded-xl p-4"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(200,81,44,0.1)',
      }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-sm font-mono"
              style={{ color: INK }}
              title={wallet.display_address}
            >
              {truncateAddr(wallet.display_address)}
            </span>
            {wallet.is_primary ? (
              <span
                className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded"
                style={{
                  background: ORANGE,
                  color: '#FFFFFF',
                }}
              >
                {t('primary')}
              </span>
            ) : null}
          </div>
          <div className="mt-2">
            {editingLabel && canEditLabel ? (
              <input
                type="text"
                value={labelDraft}
                autoFocus
                maxLength={64}
                onChange={(e) => setLabelDraft(e.target.value)}
                onBlur={() => void commitLabel()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void commitLabel()
                  } else if (e.key === 'Escape') {
                    setLabelDraft(wallet.label)
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
                onClick={() => canEditLabel && setEditingLabel(true)}
                disabled={!canEditLabel}
                title={!canEditLabel ? viewerHint : undefined}
                className="text-xs"
                style={{
                  color: wallet.label ? INK : MUTED,
                  background: 'transparent',
                  border: 'none',
                  padding: 0,
                  cursor: canEditLabel ? 'pointer' : 'default',
                  textAlign: 'left',
                }}
              >
                {wallet.label || t('addLabel')}
              </button>
            )}
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

        <div className="flex items-center gap-2 flex-shrink-0">
          {!wallet.is_primary ? (
            <button
              type="button"
              disabled={saving || !canSetPrimary}
              onClick={() => canSetPrimary && onSetPrimary()}
              title={!canSetPrimary ? adminOnlyHint : undefined}
              className="text-xs px-3 py-1.5 rounded-lg"
              style={{
                background: 'transparent',
                color: ORANGE,
                border: `1px solid ${ORANGE}`,
                cursor: saving || !canSetPrimary ? 'not-allowed' : 'pointer',
                opacity: saving || !canSetPrimary ? 0.5 : 1,
              }}
            >
              {t('makePrimary')}
            </button>
          ) : null}
          {confirmUnlink && canUnlink ? (
            <>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  setConfirmUnlink(false)
                  void onUnlink()
                }}
                className="text-xs px-3 py-1.5 rounded-lg"
                style={{
                  background: ORANGE,
                  color: '#FFFFFF',
                  border: 'none',
                  cursor: saving ? 'wait' : 'pointer',
                  opacity: saving ? 0.6 : 1,
                }}
              >
                {t('confirmUnlink')}
              </button>
              <button
                type="button"
                onClick={() => setConfirmUnlink(false)}
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
              disabled={saving || !canUnlink}
              onClick={() => canUnlink && setConfirmUnlink(true)}
              title={!canUnlink ? adminOnlyHint : undefined}
              className="text-xs px-3 py-1.5 rounded-lg"
              style={{
                background: 'transparent',
                color: MUTED,
                border: '1px solid rgba(136,135,128,0.3)',
                cursor: saving || !canUnlink ? 'not-allowed' : 'pointer',
                opacity: saving || !canUnlink ? 0.5 : 1,
              }}
            >
              {t('unlink')}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}
