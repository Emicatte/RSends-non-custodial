'use client'

import { useTranslations } from 'next-intl'
import { useMemo, useState } from 'react'
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
  'last_auth_method',
  'invalid_token',
  'user_not_found',
  'no_token',
  'session_expired',
  'unknown',
])

export function SignInMethodsSection() {
  const t = useTranslations('settings.security.signInMethods')

  const {
    methods,
    loading,
    saving,
    error,
    clearError,
    addPassword,
    removePassword,
  } = useAccountMethods()

  const [addPasswordOpen, setAddPasswordOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<RemovableMethod | null>(null)

  // Password is the only sign-in method (social login was removed), so an
  // account that has one can never remove it (last_auth_method would 409).
  const isLastMethod = methods?.has_password === true

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  async function handleConfirmRemove() {
    if (removeTarget === 'password') await removePassword()
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
