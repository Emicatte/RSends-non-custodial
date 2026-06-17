'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useUserApiKeys, type ApiKeyCreateResult } from '@/hooks/useUserApiKeys'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

const KNOWN_ERROR_CODES = new Set<string>([
  'max_keys_reached',
  'not_found',
  'unknown',
  'no_token',
  'session_expired',
  'auth_unavailable',
])

type Step = 'form' | 'display'

export function CreateApiKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated?: () => void
}) {
  const t = useTranslations('settings.apiKeys')
  const { availableScopes, loadAvailableScopes, createKey } = useUserApiKeys()

  const [step, setStep] = useState<Step>('form')
  const [label, setLabel] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ApiKeyCreateResult | null>(null)
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    void loadAvailableScopes()
  }, [loadAvailableScopes])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (step === 'display') return
      if (submitting) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, step, submitting])

  const canSubmit = label.trim().length > 0 && selectedScopes.size > 0 && !submitting

  const errorMessage = useMemo(() => {
    if (!error) return null
    const code = KNOWN_ERROR_CODES.has(error) ? error : 'unknown'
    try {
      return t(`errors.${code}`)
    } catch {
      return t('errors.unknown')
    }
  }, [error, t])

  function toggleScope(scope: string) {
    setSelectedScopes((cur) => {
      const next = new Set(cur)
      if (next.has(scope)) next.delete(scope)
      else next.add(scope)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setError(null)
    setSubmitting(true)
    try {
      const r = await createKey({
        label: label.trim(),
        scopes: Array.from(selectedScopes),
      })
      setResult(r)
      setStep('display')
    } catch (err) {
      const code = err instanceof Error ? err.message : 'unknown'
      setError(code)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCopy() {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.plaintext_key)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  function handleDone() {
    onCreated?.()
    onClose()
  }

  // Backdrop: locked during step=display to prevent accidental loss.
  function handleBackdrop() {
    if (step === 'display') return
    if (submitting) return
    onClose()
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(44,44,42,0.45)' }}
      onClick={handleBackdrop}
    >
      <div
        className="rounded-2xl w-full max-w-lg"
        style={{
          background: '#FFFFFF',
          border: `1px solid ${step === 'display' ? DANGER : ORANGE}`,
          padding: 24,
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {step === 'form' ? (
          <>
            <h2
              className="text-lg font-semibold"
              style={{ color: ORANGE, margin: 0 }}
            >
              {t('modal.createTitle')}
            </h2>

            <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
              <div>
                <label
                  className="block text-xs font-medium mb-1"
                  style={{ color: MUTED }}
                  htmlFor="api-key-label"
                >
                  {t('modal.labelLabel')}
                </label>
                <input
                  id="api-key-label"
                  type="text"
                  autoComplete="off"
                  value={label}
                  onChange={(e) => setLabel(e.target.value.slice(0, 100))}
                  placeholder={t('modal.labelPlaceholder')}
                  disabled={submitting}
                  className="w-full text-sm rounded-lg px-3 py-2"
                  style={{
                    color: INK,
                    background: '#FFFFFF',
                    border: '1px solid rgba(200,81,44,0.25)',
                    outline: 'none',
                  }}
                />
              </div>

              <div>
                <label
                  className="block text-xs font-medium mb-1"
                  style={{ color: MUTED }}
                >
                  {t('modal.scopesLabel')}
                </label>
                <p
                  className="text-xs mb-2"
                  style={{ color: MUTED }}
                >
                  {t('modal.scopesHint')}
                </p>
                <div className="flex flex-col gap-2">
                  {availableScopes.map((scope) => {
                    const checked = selectedScopes.has(scope)
                    let scopeDescription = scope
                    try {
                      scopeDescription = t(`scopes.${scope}`)
                    } catch {
                      scopeDescription = scope
                    }
                    return (
                      <label
                        key={scope}
                        className="flex items-start gap-2 text-sm cursor-pointer rounded-lg px-2 py-2"
                        style={{
                          background: checked
                            ? 'rgba(200,81,44,0.06)'
                            : 'transparent',
                          border: `1px solid ${
                            checked ? ORANGE : 'rgba(136,135,128,0.25)'
                          }`,
                          color: INK,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={submitting}
                          onChange={() => toggleScope(scope)}
                          className="mt-0.5"
                        />
                        <span className="flex flex-col">
                          <span className="font-mono text-xs" style={{ color: ORANGE }}>
                            {scope}
                          </span>
                          <span style={{ color: MUTED, fontSize: 12 }}>
                            {scopeDescription}
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              </div>

              {errorMessage ? (
                <div
                  className="rounded-lg px-3 py-2 text-sm"
                  style={{
                    background: 'rgba(192,57,43,0.06)',
                    border: `1px solid ${DANGER}`,
                    color: INK,
                  }}
                >
                  {errorMessage}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="text-sm px-4 py-2 rounded-lg"
                  style={{
                    background: 'transparent',
                    color: MUTED,
                    border: `1px solid ${MUTED}`,
                    cursor: submitting ? 'wait' : 'pointer',
                    opacity: submitting ? 0.6 : 1,
                  }}
                >
                  {t('modal.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="text-sm px-4 py-2 rounded-lg"
                  style={{
                    background: ORANGE,
                    color: '#FFFFFF',
                    border: 'none',
                    cursor: !canSubmit ? 'not-allowed' : 'pointer',
                    opacity: !canSubmit ? 0.5 : 1,
                  }}
                >
                  {submitting
                    ? t('modal.creating')
                    : t('modal.createCta')}
                </button>
              </div>
            </form>
          </>
        ) : (
          <>
            <h2
              className="text-lg font-semibold"
              style={{ color: DANGER, margin: 0 }}
            >
              {t('modal.displayTitle')}
            </h2>

            <div
              className="rounded-lg px-3 py-3 text-sm mt-4"
              style={{
                background: 'rgba(192,57,43,0.06)',
                border: `1px solid ${DANGER}`,
                color: INK,
              }}
            >
              {t('modal.saveWarning')}
            </div>

            <div className="mt-4">
              <label
                className="block text-xs font-medium mb-1"
                style={{ color: MUTED }}
              >
                {result?.label}
              </label>
              <pre
                className="w-full text-xs rounded-lg px-3 py-3 font-mono break-all whitespace-pre-wrap"
                style={{
                  color: INK,
                  background: 'rgba(44,44,42,0.04)',
                  border: '1px solid rgba(136,135,128,0.25)',
                  margin: 0,
                }}
              >
                {result?.plaintext_key}
              </pre>
              <div className="flex justify-end mt-2">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="text-xs px-3 py-1.5 rounded-lg"
                  style={{
                    background: 'transparent',
                    color: ORANGE,
                    border: `1px solid ${ORANGE}`,
                    cursor: 'pointer',
                  }}
                >
                  {copied ? t('modal.copied') : t('modal.copy')}
                </button>
              </div>
            </div>

            <label
              className="mt-4 flex items-start gap-2 text-sm cursor-pointer"
              style={{ color: INK }}
            >
              <input
                type="checkbox"
                checked={saved}
                onChange={(e) => setSaved(e.target.checked)}
                className="mt-0.5"
              />
              <span>{t('modal.savedCheckbox')}</span>
            </label>

            <div className="flex items-center justify-end mt-4">
              <button
                type="button"
                onClick={handleDone}
                disabled={!saved}
                className="text-sm px-4 py-2 rounded-lg"
                style={{
                  background: ORANGE,
                  color: '#FFFFFF',
                  border: 'none',
                  cursor: !saved ? 'not-allowed' : 'pointer',
                  opacity: !saved ? 0.5 : 1,
                }}
              >
                {t('modal.done')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
