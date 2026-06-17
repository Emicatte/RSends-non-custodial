'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useTranslations, useLocale } from 'next-intl'
import {
  useMerchantProfile,
  type MerchantProfileInput,
} from '@/hooks/useMerchantProfile'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'
const SUCCESS = '#1E7F5C'

// Codici errore con messaggio i18n dedicato; tutto il resto → 'generic'.
const KNOWN_ERRORS = [
  'no_primary_wallet',
  'invalid_email',
  'session_not_ready',
  'session_expired',
  'insufficient_role',
]

const EMPTY: MerchantProfileInput = {
  billing_legal_name: '',
  billing_vat_number: '',
  billing_tax_code: '',
  billing_address_line: '',
  billing_city: '',
  billing_postal_code: '',
  billing_country: '',
  billing_email: '',
  billing_pec: '',
}

// (field key, i18n label key, optional flag, type)
const FIELDS: Array<{ key: keyof MerchantProfileInput; label: string; optional?: boolean; type?: string }> = [
  { key: 'billing_legal_name', label: 'legalName' },
  { key: 'billing_vat_number', label: 'vatNumber' },
  { key: 'billing_tax_code', label: 'taxCode', optional: true },
  { key: 'billing_address_line', label: 'addressLine' },
  { key: 'billing_city', label: 'city' },
  { key: 'billing_postal_code', label: 'postalCode' },
  { key: 'billing_country', label: 'country' },
  { key: 'billing_email', label: 'email', type: 'email' },
  { key: 'billing_pec', label: 'pec', optional: true, type: 'email' },
]

export function BillingSettings() {
  const t = useTranslations('settings.billing')
  const locale = useLocale()
  const {
    profile,
    loading,
    saving,
    error,
    noPrimaryWallet,
    isAuthed,
    currentUserRole,
    save,
    clearError,
  } = useMerchantProfile()

  const [form, setForm] = useState<MerchantProfileInput>(EMPTY)
  const [savedOk, setSavedOk] = useState(false)

  const canWrite = currentUserRole === 'admin' || currentUserRole === 'operator'

  // Precompila il form quando arriva il profilo dal GET.
  useEffect(() => {
    if (!profile) return
    setForm({
      billing_legal_name: profile.billing_legal_name ?? '',
      billing_vat_number: profile.billing_vat_number ?? '',
      billing_tax_code: profile.billing_tax_code ?? '',
      billing_address_line: profile.billing_address_line ?? '',
      billing_city: profile.billing_city ?? '',
      billing_postal_code: profile.billing_postal_code ?? '',
      billing_country: profile.billing_country ?? '',
      billing_email: profile.billing_email ?? '',
      billing_pec: profile.billing_pec ?? '',
    })
  }, [profile])

  const onChange = (key: keyof MerchantProfileInput, value: string) => {
    setSavedOk(false)
    if (error) clearError()
    setForm((f) => ({ ...f, [key]: value }))
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavedOk(false)
    const ok = await save(form)
    if (ok) setSavedOk(true)
  }

  if (!isAuthed) {
    return <div style={{ color: MUTED }}>{t('loading')}</div>
  }

  const header = (
    <header>
      <h1 className="text-2xl font-semibold" style={{ color: INK }}>
        {t('title')}
      </h1>
      <p className="text-sm mt-2" style={{ color: MUTED }}>
        {t('description')}
      </p>
    </header>
  )

  // Caso: nessun wallet primario → niente form, invito a collegare un wallet.
  if (noPrimaryWallet) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl">
        {header}
        <div
          style={{
            background: 'rgba(200,81,44,0.06)',
            border: `1px solid ${ORANGE}`,
            borderRadius: 8,
            padding: 16,
            color: INK,
          }}
        >
          <p className="text-sm font-medium mb-1">{t('noWallet.title')}</p>
          <p className="text-sm mb-3" style={{ color: MUTED }}>
            {t('noWallet.body')}
          </p>
          <Link
            href={`/${locale}/settings/wallets`}
            className="inline-block text-sm font-medium"
            style={{ color: ORANGE, textDecoration: 'none' }}
          >
            {t('noWallet.cta')} →
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      {header}

      {/* Nota: spiega al cliente perché compila questi dati. */}
      <div
        style={{
          background: 'rgba(44,44,42,0.04)',
          border: `1px solid rgba(44,44,42,0.10)`,
          borderRadius: 8,
          padding: 12,
          color: INK,
        }}
      >
        <p className="text-sm">{t('infoBanner')}</p>
      </div>

      {error && (
        <div
          style={{
            background: 'rgba(192,57,43,0.06)',
            border: `1px solid ${DANGER}`,
            borderRadius: 8,
            padding: 12,
            color: INK,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span className="text-sm">
            {t(`errors.${KNOWN_ERRORS.includes(error) ? error : 'generic'}`)}
          </span>
          <button onClick={clearError} aria-label="dismiss" style={{ color: MUTED }}>
            ×
          </button>
        </div>
      )}

      {savedOk && !error && (
        <div
          style={{
            background: 'rgba(30,127,92,0.07)',
            border: `1px solid ${SUCCESS}`,
            borderRadius: 8,
            padding: 12,
            color: INK,
          }}
        >
          <span className="text-sm">{t('saved')}</span>
        </div>
      )}

      {loading ? (
        <div style={{ color: MUTED }}>{t('loading')}</div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {FIELDS.map((f) => (
              <label key={f.key} className="flex flex-col gap-1">
                <span className="text-sm font-medium" style={{ color: INK }}>
                  {t(`fields.${f.label}`)}
                  {f.optional && (
                    <span className="ml-1 text-xs" style={{ color: MUTED }}>
                      ({t('optional')})
                    </span>
                  )}
                </span>
                <input
                  type={f.type ?? 'text'}
                  value={form[f.key]}
                  onChange={(e) => onChange(f.key, e.target.value)}
                  disabled={!canWrite || saving}
                  className="px-3 py-2 rounded-lg text-sm"
                  style={{
                    border: '1px solid rgba(44,44,42,0.18)',
                    background: !canWrite ? 'rgba(44,44,42,0.03)' : '#FFFFFF',
                    color: INK,
                  }}
                />
              </label>
            ))}
          </div>

          {!canWrite && (
            <p className="text-sm" style={{ color: MUTED }}>
              {t('readOnly')}
            </p>
          )}

          <div>
            <button
              type="submit"
              disabled={!canWrite || saving}
              style={{
                background: ORANGE,
                color: '#FFFFFF',
                border: 'none',
                borderRadius: 8,
                padding: '8px 20px',
                cursor: !canWrite || saving ? 'not-allowed' : 'pointer',
                opacity: !canWrite || saving ? 0.5 : 1,
                fontWeight: 600,
              }}
            >
              {saving ? t('saving') : t('save')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
