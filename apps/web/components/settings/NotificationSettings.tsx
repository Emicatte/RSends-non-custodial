'use client'

import { useTranslations } from 'next-intl'
import { useNotificationPreferences } from '@/hooks/useNotificationPreferences'

type BoolKey =
  | 'email_login_new_device'
  | 'telegram_tx_confirmed'
  | 'telegram_tx_failed'
  | 'telegram_price_alerts'

export function NotificationSettings() {
  const t = useTranslations('settings.notifications')
  const { preferences, loading, saving, toggle } = useNotificationPreferences()

  if (loading || !preferences) {
    return (
      <div className="text-sm" style={{ color: '#888780' }}>
        {t('loading')}
      </div>
    )
  }

  return (
    <div className="space-y-10">
      <section>
        <h2
          className="text-xl font-semibold mb-1"
          style={{ color: '#2C2C2A' }}
        >
          {t('email.title')}
        </h2>
        <p className="text-sm mb-4" style={{ color: '#888780' }}>
          {t('email.description')}
        </p>
        <ToggleRow
          label={t('email.loginNewDevice.label')}
          description={t('email.loginNewDevice.description')}
          checked={preferences.email_login_new_device}
          disabled={saving}
          onChange={(v) => toggle('email_login_new_device', v)}
        />
      </section>

      <section>
        <h2
          className="text-xl font-semibold mb-1"
          style={{ color: '#2C2C2A' }}
        >
          {t('telegram.title')}
        </h2>
        <p className="text-sm mb-4" style={{ color: '#888780' }}>
          {t('telegram.description')}
        </p>
        <div
          className="rounded-xl p-4"
          style={{
            background: 'rgba(200,81,44,0.04)',
            border: '1px dashed rgba(200,81,44,0.25)',
          }}
        >
          <p
            className="text-sm font-medium mb-1"
            style={{ color: '#2C2C2A' }}
          >
            {t('telegram.comingSoon.title')}
          </p>
          <p className="text-xs" style={{ color: '#888780' }}>
            {t('telegram.comingSoon.description')}
          </p>
        </div>
      </section>
    </div>
  )
}

function ToggleRow({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string
  description: string
  checked: boolean
  disabled: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div
      className="flex items-start justify-between gap-6 py-4"
      style={{ borderBottom: '1px solid rgba(200,81,44,0.1)' }}
    >
      <div>
        <div className="text-sm font-medium" style={{ color: '#2C2C2A' }}>
          {label}
        </div>
        <div
          className="text-xs mt-1 max-w-md"
          style={{ color: '#888780' }}
        >
          {description}
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        style={{
          position: 'relative',
          width: 40,
          height: 22,
          borderRadius: 11,
          background: checked ? '#C8512C' : 'rgba(200,81,44,0.2)',
          transition: 'background 150ms',
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? 'wait' : 'pointer',
          border: 'none',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 3,
            left: checked ? 21 : 3,
            width: 16,
            height: 16,
            borderRadius: 8,
            background: '#FFFFFF',
            transition: 'left 150ms',
            boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
          }}
        />
      </button>
    </div>
  )
}
