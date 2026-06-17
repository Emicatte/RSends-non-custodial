'use client'

import { signIn, useSession } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useAccountMethods } from '@/hooks/useAccountMethods'
import { AddPasswordModal } from './AddPasswordModal'
import {
  ConfirmRemoveModal,
  type RemovableMethod,
} from './ConfirmRemoveModal'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'

const KNOWN_ERROR_CODES = new Set<string>([
  'password_already_set',
  'password_not_set',
  'google_already_linked',
  'google_not_linked',
  'github_already_linked',
  'github_not_linked',
  'google_sub_in_use',
  'github_sub_in_use',
  'email_mismatch',
  'last_auth_method',
  'invalid_token',
  'user_not_found',
  'no_token',
  'session_expired',
  'unknown',
])

export function SignInMethodsSection() {
  const t = useTranslations('settings.security.signInMethods')
  const { data: session } = useSession()
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const locale = useLocale()

  const {
    methods,
    loading,
    saving,
    error,
    clearError,
    addPassword,
    removePassword,
    linkGoogle,
    unlinkGoogle,
    linkGithub,
    unlinkGithub,
  } = useAccountMethods()

  const [addPasswordOpen, setAddPasswordOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<RemovableMethod | null>(null)
  const [linkingStatus, setLinkingStatus] = useState<string | null>(null)
  const linkingHandled = useRef(false)

  const linkingQuery = searchParams?.get('linking') ?? null

  // Handle OAuth callback ?linking=google|github.
  useEffect(() => {
    if (!linkingQuery || linkingHandled.current) return
    const sess = session as
      | { id_token?: string; github_access_token?: string; access_token?: string }
      | null
    if (!sess?.access_token) return

    const idToken = sess.id_token
    const ghToken = sess.github_access_token

    if (linkingQuery === 'google' && idToken) {
      linkingHandled.current = true
      setLinkingStatus(t('linkingGoogle'))
      linkGoogle(idToken)
        .catch(() => {})
        .finally(() => {
          setLinkingStatus(null)
          router.replace(pathname ?? `/${locale}/settings/security`)
        })
    } else if (linkingQuery === 'github' && ghToken) {
      linkingHandled.current = true
      setLinkingStatus(t('linkingGithub'))
      linkGithub(ghToken)
        .catch(() => {})
        .finally(() => {
          setLinkingStatus(null)
          router.replace(pathname ?? `/${locale}/settings/security`)
        })
    }
  }, [
    linkingQuery,
    session,
    linkGoogle,
    linkGithub,
    router,
    pathname,
    locale,
    t,
  ])

  const methodCount =
    (methods?.has_password ? 1 : 0) +
    (methods?.has_google ? 1 : 0) +
    (methods?.has_github ? 1 : 0)
  const isLastMethod = methodCount === 1

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  function startLinkGoogle() {
    const cb = `/${locale}/settings/security?linking=google`
    void signIn('google', { callbackUrl: cb })
  }

  function startLinkGithub() {
    const cb = `/${locale}/settings/security?linking=github`
    void signIn('github', { callbackUrl: cb })
  }

  async function handleConfirmRemove() {
    if (!removeTarget) return
    if (removeTarget === 'password') await removePassword()
    else if (removeTarget === 'google') await unlinkGoogle()
    else if (removeTarget === 'github') await unlinkGithub()
  }

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2
          className="text-base font-semibold"
          style={{ color: INK, margin: 0 }}
        >
          {t('title')}
        </h2>
        <p className="text-sm mt-1" style={{ color: MUTED }}>
          {t('subtitle')}
        </p>
      </div>

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

      {linkingStatus ? (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'rgba(200,81,44,0.06)',
            border: '1px solid rgba(200,81,44,0.2)',
            color: INK,
          }}
        >
          {linkingStatus}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm" style={{ color: MUTED }}>
          {t('loading')}
        </p>
      ) : methods ? (
        <ul className="space-y-2">
          <MethodRow
            label={t('password')}
            status={
              methods.has_password ? t('passwordEnabled') : t('passwordNotSet')
            }
            active={methods.has_password}
            saving={saving}
            actionLabel={
              methods.has_password ? t('removePassword') : t('addPassword')
            }
            disabled={methods.has_password && isLastMethod}
            disabledTooltip={t('lastMethodTooltip')}
            onAction={() => {
              if (methods.has_password) setRemoveTarget('password')
              else setAddPasswordOpen(true)
            }}
          />
          <MethodRow
            label={t('google')}
            status={
              methods.has_google
                ? t('googleConnected', { email: methods.google_email ?? '' })
                : t('googleNotConnected')
            }
            active={methods.has_google}
            saving={saving}
            actionLabel={
              methods.has_google ? t('disconnectGoogle') : t('connectGoogle')
            }
            disabled={methods.has_google && isLastMethod}
            disabledTooltip={t('lastMethodTooltip')}
            onAction={() => {
              if (methods.has_google) setRemoveTarget('google')
              else startLinkGoogle()
            }}
          />
          <MethodRow
            label={t('github')}
            status={
              methods.has_github
                ? t('githubConnected', {
                    username: methods.github_username ?? '',
                  })
                : t('githubNotConnected')
            }
            active={methods.has_github}
            saving={saving}
            actionLabel={
              methods.has_github ? t('disconnectGithub') : t('connectGithub')
            }
            disabled={methods.has_github && isLastMethod}
            disabledTooltip={t('lastMethodTooltip')}
            onAction={() => {
              if (methods.has_github) setRemoveTarget('github')
              else startLinkGithub()
            }}
          />
        </ul>
      ) : null}

      {addPasswordOpen ? (
        <AddPasswordModal
          onSubmit={async (pw) => {
            await addPassword(pw)
          }}
          onClose={() => setAddPasswordOpen(false)}
        />
      ) : null}

      {removeTarget ? (
        <ConfirmRemoveModal
          method={removeTarget}
          onConfirm={handleConfirmRemove}
          onClose={() => setRemoveTarget(null)}
        />
      ) : null}
    </section>
  )
}

function MethodRow({
  label,
  status,
  active,
  saving,
  actionLabel,
  disabled,
  disabledTooltip,
  onAction,
}: {
  label: string
  status: string
  active: boolean
  saving: boolean
  actionLabel: string
  disabled: boolean
  disabledTooltip: string
  onAction: () => void
}) {
  return (
    <li
      className="rounded-xl p-4 flex items-start justify-between gap-4 flex-wrap"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(200,81,44,0.15)',
      }}
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium" style={{ color: INK }}>
          {label}
        </p>
        <p
          className="text-xs mt-1"
          style={{ color: active ? ORANGE : MUTED }}
        >
          {status}
        </p>
      </div>
      <button
        type="button"
        disabled={saving || disabled}
        title={disabled ? disabledTooltip : undefined}
        onClick={onAction}
        className="text-sm px-3 py-1.5 rounded-lg"
        style={{
          background: 'transparent',
          color: disabled ? MUTED : ORANGE,
          border: `1px solid ${disabled ? MUTED : ORANGE}`,
          cursor: disabled ? 'not-allowed' : saving ? 'wait' : 'pointer',
          opacity: disabled ? 0.5 : saving ? 0.6 : 1,
        }}
      >
        {actionLabel}
      </button>
    </li>
  )
}
