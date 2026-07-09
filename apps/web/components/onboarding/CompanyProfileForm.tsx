'use client'

/**
 * Company info step — one page, two visible sections (Company identity,
 * Operations) plus the declarations block. Server-side autosave: field edits
 * accumulate and flush as ONE debounced PATCH (700ms after the last change,
 * also on blur), so a partial draft resumes across sessions and devices.
 * Explicit submit finalizes; the backend re-validates completeness (422) and
 * the two must-be-true declarations. has_pep is a required yes/no radio, not
 * a checkbox (a disclosure, not a declaration).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'
import { useRouter } from '@/i18n/navigation'
import { countryOptions } from '@/lib/countries'
import {
  getCompanyProfile,
  patchCompanyProfile,
  submitCompanyProfile,
} from '@/lib/onboarding-client'
import type { CompanyProfilePatch } from '@/lib/onboarding'
import { toast } from '@/hooks/useToast'

const DEBOUNCE_MS = 700

const CATEGORIES = [
  'ecommerce',
  'saas',
  'marketplace',
  'professional_services',
  'legal_corporate_services',
  'travel',
  'education',
  'gaming',
  'nonprofit',
  'other',
] as const

const VOLUMES = ['lt_10k', '10k_100k', '100k_1m', 'gt_1m'] as const
const STABLECOINS = ['USDC', 'USDT', 'EURC'] as const

type Draft = {
  legal_name: string
  trading_name: string
  country: string
  registration_number: string
  tax_or_vat_number: string
  website: string
  business_category: string
  expected_monthly_volume: string
  countries_served: string[]
  primary_stablecoin: string
  no_sanctioned_countries: boolean
  no_prohibited_activities: boolean
  has_pep: boolean | null
}

const EMPTY: Draft = {
  legal_name: '',
  trading_name: '',
  country: '',
  registration_number: '',
  tax_or_vat_number: '',
  website: '',
  business_category: '',
  expected_monthly_volume: '',
  countries_served: [],
  primary_stablecoin: '',
  no_sanctioned_countries: false,
  no_prohibited_activities: false,
  has_pep: null,
}

const inputClass =
  'w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-[#C8512C]'
const inputStyle = { borderColor: '#DDDCD6', background: '#FFFFFF', color: '#2C2C2A' }
const labelClass = 'block text-xs font-medium mb-1'
const labelStyle = { color: '#888780' }

export function CompanyProfileForm() {
  const t = useTranslations('onboarding.company')
  const router = useRouter()
  const { data: session } = useSession()
  const locale = useLocale()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(false)

  const pendingRef = useRef<CompanyProfilePatch>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load (or start) the draft. A submitted profile means this step is done.
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!tokenRef.current) {
        setLoading(false)
        return
      }
      try {
        const profile = await getCompanyProfile(tokenRef.current)
        if (cancelled) return
        if (profile.submitted_at) {
          router.replace('/app')
          return
        }
        setDraft({
          legal_name: profile.legal_name ?? '',
          trading_name: profile.trading_name ?? '',
          country: profile.country ?? '',
          registration_number: profile.registration_number ?? '',
          tax_or_vat_number: profile.tax_or_vat_number ?? '',
          website: profile.website ?? '',
          business_category: profile.business_category ?? '',
          expected_monthly_volume: profile.expected_monthly_volume ?? '',
          countries_served: profile.countries_served ?? [],
          primary_stablecoin: profile.primary_stablecoin ?? '',
          no_sanctioned_countries: profile.no_sanctioned_countries ?? false,
          no_prohibited_activities: profile.no_prohibited_activities ?? false,
          has_pep: profile.has_pep,
        })
      } catch (e) {
        if (cancelled) return
        if ((e as Error).message !== 'not_found') setLoadError(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const flush = useCallback(async () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const pending = pendingRef.current
    if (Object.keys(pending).length === 0) return
    pendingRef.current = {}
    setSaving(true)
    try {
      await patchCompanyProfile(tokenRef.current, pending)
    } catch (e) {
      // Autosave is best-effort; the explicit submit re-validates everything.
      console.error('[CompanyProfileForm] autosave', e)
    } finally {
      setSaving(false)
    }
  }, [])

  const queueSave = useCallback(
    (patch: CompanyProfilePatch) => {
      pendingRef.current = { ...pendingRef.current, ...patch }
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        void flush()
      }, DEBOUNCE_MS)
    },
    [flush],
  )

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    [],
  )

  const setField = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }))
    // Empty strings stay local-only: the API rejects empty values (min_length)
    // and an unfilled field is simply an incomplete draft.
    const wireValue =
      typeof value === 'string' && value === '' ? undefined : value
    if (wireValue !== undefined) {
      queueSave({ [key]: wireValue } as CompanyProfilePatch)
    }
  }

  const canSubmit =
    draft.no_sanctioned_countries &&
    draft.no_prohibited_activities &&
    draft.has_pep !== null &&
    !submitting

  const onSubmit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setSubmitError(false)
    try {
      await flush()
      await submitCompanyProfile(tokenRef.current)
      toast.success(t('successToast'))
      router.replace('/app')
    } catch {
      setSubmitError(true)
      setSubmitting(false)
    }
  }

  if (loading) return null
  if (loadError) {
    return (
      <p className="text-sm" role="alert" style={{ color: '#B3261E' }}>
        {t('loadError')}
      </p>
    )
  }

  const countries = countryOptions(locale)

  return (
    <div className="space-y-8">
      {/* ── Company identity ─────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold" style={{ color: '#2C2C2A' }}>
          {t('sections.identity')}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="cp-legal-name" className={labelClass} style={labelStyle}>
              {t('fields.legalName')}
            </label>
            <input
              id="cp-legal-name"
              type="text"
              maxLength={200}
              value={draft.legal_name}
              onChange={(e) => setField('legal_name', e.target.value)}
              onBlur={() => void flush()}
              className={inputClass}
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="cp-trading-name" className={labelClass} style={labelStyle}>
              {t('fields.tradingName')}
            </label>
            <input
              id="cp-trading-name"
              type="text"
              maxLength={200}
              value={draft.trading_name}
              onChange={(e) => setField('trading_name', e.target.value)}
              onBlur={() => void flush()}
              className={inputClass}
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="cp-country" className={labelClass} style={labelStyle}>
              {t('fields.country')}
            </label>
            <select
              id="cp-country"
              value={draft.country}
              onChange={(e) => setField('country', e.target.value)}
              className={inputClass}
              style={inputStyle}
            >
              <option value="" disabled>
                {t('fields.selectPlaceholder')}
              </option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cp-reg-number" className={labelClass} style={labelStyle}>
              {t('fields.registrationNumber')}
            </label>
            <input
              id="cp-reg-number"
              type="text"
              maxLength={100}
              value={draft.registration_number}
              onChange={(e) => setField('registration_number', e.target.value)}
              onBlur={() => void flush()}
              className={inputClass}
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="cp-tax-number" className={labelClass} style={labelStyle}>
              {t('fields.taxOrVatNumber')}
            </label>
            <input
              id="cp-tax-number"
              type="text"
              maxLength={100}
              value={draft.tax_or_vat_number}
              onChange={(e) => setField('tax_or_vat_number', e.target.value)}
              onBlur={() => void flush()}
              className={inputClass}
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="cp-website" className={labelClass} style={labelStyle}>
              {t('fields.website')}
            </label>
            <input
              id="cp-website"
              type="url"
              maxLength={2048}
              placeholder="https://"
              value={draft.website}
              onChange={(e) => setField('website', e.target.value)}
              onBlur={() => void flush()}
              className={inputClass}
              style={inputStyle}
            />
          </div>
        </div>
      </section>

      {/* ── Operations ───────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold" style={{ color: '#2C2C2A' }}>
          {t('sections.operations')}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="cp-category" className={labelClass} style={labelStyle}>
              {t('fields.businessCategory')}
            </label>
            <select
              id="cp-category"
              value={draft.business_category}
              onChange={(e) => setField('business_category', e.target.value)}
              className={inputClass}
              style={inputStyle}
            >
              <option value="" disabled>
                {t('fields.selectPlaceholder')}
              </option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`categories.${c}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cp-volume" className={labelClass} style={labelStyle}>
              {t('fields.expectedMonthlyVolume')}
            </label>
            <select
              id="cp-volume"
              value={draft.expected_monthly_volume}
              onChange={(e) => setField('expected_monthly_volume', e.target.value)}
              className={inputClass}
              style={inputStyle}
            >
              <option value="" disabled>
                {t('fields.selectPlaceholder')}
              </option>
              {VOLUMES.map((v) => (
                <option key={v} value={v}>
                  {t(`volumes.${v}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cp-stablecoin" className={labelClass} style={labelStyle}>
              {t('fields.primaryStablecoin')}
            </label>
            <select
              id="cp-stablecoin"
              value={draft.primary_stablecoin}
              onChange={(e) => setField('primary_stablecoin', e.target.value)}
              className={inputClass}
              style={inputStyle}
            >
              <option value="" disabled>
                {t('fields.selectPlaceholder')}
              </option>
              {STABLECOINS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cp-countries-served" className={labelClass} style={labelStyle}>
              {t('fields.countriesServed')}
            </label>
            <select
              id="cp-countries-served"
              value=""
              onChange={(e) => {
                const code = e.target.value
                if (!code || draft.countries_served.includes(code)) return
                setField('countries_served', [...draft.countries_served, code])
              }}
              className={inputClass}
              style={inputStyle}
            >
              <option value="">{t('fields.addCountry')}</option>
              {countries
                .filter((c) => !draft.countries_served.includes(c.code))
                .map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
            </select>
            {draft.countries_served.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {draft.countries_served.map((code) => (
                  <button
                    key={code}
                    type="button"
                    aria-label={t('fields.removeCountry').replace('{country}', code)}
                    onClick={() =>
                      setField(
                        'countries_served',
                        draft.countries_served.filter((c) => c !== code),
                      )
                    }
                    className="rounded-full border px-2.5 py-0.5 text-xs"
                    style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
                  >
                    {code} ×
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Declarations ─────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold" style={{ color: '#2C2C2A' }}>
          {t('sections.declarations')}
        </h2>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={draft.no_sanctioned_countries}
            onChange={(e) => setField('no_sanctioned_countries', e.target.checked)}
            className="mt-1 h-4 w-4 shrink-0 accent-[#C8512C]"
          />
          <span className="text-sm" style={{ color: '#2C2C2A' }}>
            {t('declaration1')}
          </span>
        </label>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={draft.no_prohibited_activities}
            onChange={(e) => setField('no_prohibited_activities', e.target.checked)}
            className="mt-1 h-4 w-4 shrink-0 accent-[#C8512C]"
          />
          <span className="text-sm" style={{ color: '#2C2C2A' }}>
            {t('declaration2')}
          </span>
        </label>
        <fieldset>
          <legend className="text-sm mb-2" style={{ color: '#2C2C2A' }}>
            {t('pepQuestion')}
          </legend>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 cursor-pointer text-sm" style={{ color: '#2C2C2A' }}>
              <input
                type="radio"
                name="has_pep"
                checked={draft.has_pep === true}
                onChange={() => setField('has_pep', true)}
                className="h-4 w-4 accent-[#C8512C]"
              />
              {t('yes')}
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm" style={{ color: '#2C2C2A' }}>
              <input
                type="radio"
                name="has_pep"
                checked={draft.has_pep === false}
                onChange={() => setField('has_pep', false)}
                className="h-4 w-4 accent-[#C8512C]"
              />
              {t('no')}
            </label>
          </div>
        </fieldset>
      </section>

      {submitError && (
        <p className="text-sm" role="alert" style={{ color: '#B3261E' }}>
          {t('incomplete')}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          className="rounded-lg px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ background: '#C8512C' }}
        >
          {t('submit')}
        </button>
        <span className="text-xs" style={{ color: '#888780' }} aria-live="polite">
          {saving ? t('saving') : ''}
        </span>
      </div>
    </div>
  )
}
