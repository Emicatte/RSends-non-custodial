'use client'

import { useEffect, useState } from 'react'
import {
  useMerchantApiKeys,
  type MerchantKeyCreateResult,
  type MerchantKeyItem,
} from '@/hooks/useMerchantApiKeys'

/**
 * Merchant API keys (rsend_) — session-minted (Option B, 2026-07-15).
 *
 * The real payment-API keys, minted from the logged-in session: the backend
 * resolves the org's owner address (settlement wallet / linked wallet) and
 * pins environment=test, scope=write. Replaces the old dead-end banner that
 * pointed at the wallet-authenticated Merchant Dashboard.
 *
 * Copy is intentionally hardcoded English, like the banner it replaces
 * (this page is not localized yet).
 */

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'
const BORDER = 'rgba(200,81,44,0.1)'

export function MerchantApiKeys() {
  const {
    keys,
    maxAllowed,
    remainingSlots,
    ownerAddress,
    loading,
    saving,
    error,
    currentUserRole,
    revokeKey,
    reload,
  } = useMerchantApiKeys()

  const [modalOpen, setModalOpen] = useState(false)
  const [confirmRevokeId, setConfirmRevokeId] = useState<number | null>(null)

  const isAdmin = currentUserRole === 'admin'

  return (
    <section
      className="rounded-xl p-5 flex flex-col gap-4"
      style={{ background: '#FFFFFF', border: `1px solid ${BORDER}` }}
    >
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold m-0" style={{ color: INK }}>
            Merchant API keys{' '}
            <code className="text-xs" style={{ color: ORANGE }}>
              rsend_test_
            </code>
          </h2>
          <p className="text-xs mt-1 m-0" style={{ color: MUTED }}>
            These keys call the merchant payment API — create payment intents,
            register webhooks, list transactions. Test environment (Base
            Sepolia). {remainingSlots} of {maxAllowed} slots free.
          </p>
        </div>
        {isAdmin ? (
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            disabled={loading || saving || error === 'no_primary_wallet'}
            className="text-sm px-4 py-2 rounded-lg"
            style={{
              background: ORANGE,
              color: '#FFFFFF',
              border: 'none',
              cursor: 'pointer',
              opacity: loading || error === 'no_primary_wallet' ? 0.5 : 1,
            }}
          >
            Create merchant key
          </button>
        ) : (
          <span className="text-xs" style={{ color: MUTED }}>
            Only org admins can mint merchant keys.
          </span>
        )}
      </header>

      {error === 'no_primary_wallet' ? (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'rgba(217,122,46,0.08)',
            border: '1px solid #D97A2E',
            color: INK,
          }}
        >
          <strong>Set your settlement wallet first.</strong> Merchant keys are
          bound to the address your payments settle to. Add it in{' '}
          <a href="/settings" style={{ color: ORANGE, fontWeight: 600 }}>
            Settings
          </a>{' '}
          (or link a wallet), then come back here.
        </div>
      ) : error === 'settlement_wallet_conflict' ? (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'rgba(192,57,43,0.06)',
            border: `1px solid ${DANGER}`,
            color: INK,
          }}
        >
          Your settlement wallet is already claimed by another account, so this
          org&rsquo;s merchant identity is contested. Link the wallet via SIWE in{' '}
          <a href="/settings/wallets" style={{ color: ORANGE, fontWeight: 600 }}>
            Settings → Wallets
          </a>{' '}
          to prove ownership, or use a different settlement address.
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm m-0" style={{ color: MUTED }}>
          Loading…
        </p>
      ) : keys.length === 0 && !error ? (
        <p className="text-sm m-0" style={{ color: MUTED }}>
          No merchant keys yet.
          {isAdmin ? ' Create one to call the payment API.' : ''}
        </p>
      ) : (
        <ul className="flex flex-col gap-2 list-none p-0 m-0">
          {keys.map((k) => (
            <MerchantKeyRow
              key={k.id}
              item={k}
              canRevoke={isAdmin}
              saving={saving}
              confirming={confirmRevokeId === k.id}
              onAskRevoke={() => setConfirmRevokeId(k.id)}
              onCancelRevoke={() => setConfirmRevokeId(null)}
              onConfirmRevoke={async () => {
                await revokeKey(k.id)
                setConfirmRevokeId(null)
              }}
            />
          ))}
        </ul>
      )}

      {ownerAddress ? (
        <p className="text-xs m-0" style={{ color: MUTED }}>
          Keys are bound to your merchant identity{' '}
          <code className="font-mono">{ownerAddress}</code> — the same scope the
          payment API and dashboard read from.
        </p>
      ) : null}

      <UsageSnippet />

      {modalOpen ? (
        <CreateMerchantKeyModal
          onClose={() => setModalOpen(false)}
          onCreated={() => void reload()}
        />
      ) : null}
    </section>
  )
}

function MerchantKeyRow({
  item,
  canRevoke,
  saving,
  confirming,
  onAskRevoke,
  onCancelRevoke,
  onConfirmRevoke,
}: {
  item: MerchantKeyItem
  canRevoke: boolean
  saving: boolean
  confirming: boolean
  onAskRevoke: () => void
  onCancelRevoke: () => void
  onConfirmRevoke: () => Promise<void>
}) {
  const revoked = !item.is_active
  return (
    <li
      className="rounded-lg px-3 py-2 flex items-center justify-between gap-3 flex-wrap"
      style={{
        border: '1px solid rgba(136,135,128,0.25)',
        opacity: revoked ? 0.55 : 1,
      }}
    >
      <div className="flex flex-col">
        <span className="text-sm" style={{ color: INK }}>
          {item.label}{' '}
          {!item.session_minted ? (
            <span className="text-xs" style={{ color: MUTED }}>
              (wallet-minted)
            </span>
          ) : null}
        </span>
        <code className="text-xs font-mono" style={{ color: MUTED }}>
          {item.prefix}… · {item.environment} · {item.scope}
          {revoked ? ' · revoked' : ''}
        </code>
      </div>
      {canRevoke && !revoked ? (
        confirming ? (
          <span className="flex items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void onConfirmRevoke()}
              className="text-xs px-3 py-1.5 rounded-lg"
              style={{
                background: DANGER,
                color: '#FFFFFF',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Confirm revoke
            </button>
            <button
              type="button"
              onClick={onCancelRevoke}
              className="text-xs px-3 py-1.5 rounded-lg"
              style={{
                background: 'transparent',
                color: MUTED,
                border: `1px solid ${MUTED}`,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={onAskRevoke}
            className="text-xs px-3 py-1.5 rounded-lg"
            style={{
              background: 'transparent',
              color: DANGER,
              border: `1px solid ${DANGER}`,
              cursor: 'pointer',
            }}
          >
            Revoke
          </button>
        )
      ) : null}
    </li>
  )
}

function UsageSnippet() {
  return (
    <section
      className="rounded-xl p-4"
      style={{ background: '#FFFFFF', border: `1px solid ${BORDER}` }}
    >
      <h3 className="text-sm font-semibold m-0" style={{ color: INK }}>
        Use your key
      </h3>
      <p className="text-xs mt-2 m-0" style={{ color: MUTED }}>
        Create a test payment intent on Base Sepolia:
      </p>
      <pre
        className="text-xs font-mono rounded-lg px-3 py-3 mt-3 whitespace-pre-wrap break-all m-0"
        style={{
          color: INK,
          background: 'rgba(44,44,42,0.04)',
          border: '1px solid rgba(136,135,128,0.25)',
        }}
      >{`curl -X POST https://rsends-non-custodial.onrender.com/api/v1/merchant/payment-intent \\
  -H "Authorization: Bearer rsend_test_..." \\
  -H "Content-Type: application/json" \\
  -d '{"amount": "10.00", "currency": "USDC", "chain": "base-sepolia"}'`}</pre>
    </section>
  )
}

/** Two-step create modal — same escape-locked display-step pattern as
 * CreateApiKeyModal (the plaintext is shown once and must be acknowledged). */
function CreateMerchantKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated?: () => void
}) {
  const { createKey } = useMerchantApiKeys()
  const [step, setStep] = useState<'form' | 'display'>('form')
  const [label, setLabel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<MerchantKeyCreateResult | null>(null)
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  const canSubmit = label.trim().length > 0 && !submitting

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (step === 'display' || submitting) return // plaintext must be acknowledged
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, step, submitting])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setError(null)
    setSubmitting(true)
    try {
      const r = await createKey(label.trim())
      setResult(r)
      setStep('display')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'unknown')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCopy() {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.key)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const errorText =
    error === 'max_keys_reached'
      ? 'You already have 5 active test keys — revoke one first.'
      : error === 'no_primary_wallet'
        ? 'Set your settlement wallet in Settings first.'
        : error === 'settlement_wallet_conflict'
          ? 'Your settlement wallet is claimed by another account — see the note on the keys page.'
          : error
            ? 'Something went wrong. Try again.'
            : null

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(44,44,42,0.45)' }}
      onClick={() => {
        if (step !== 'display' && !submitting) onClose()
      }}
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
            <h2 className="text-lg font-semibold m-0" style={{ color: ORANGE }}>
              Create merchant API key
            </h2>
            <p className="text-xs mt-2" style={{ color: MUTED }}>
              A <code>rsend_test_</code> key with write scope — it can create
              and cancel payment intents and register webhooks on the test
              environment.
            </p>
            <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
              <div>
                <label
                  className="block text-xs font-medium mb-1"
                  style={{ color: MUTED }}
                  htmlFor="merchant-key-label"
                >
                  Label
                </label>
                <input
                  id="merchant-key-label"
                  type="text"
                  autoComplete="off"
                  value={label}
                  onChange={(e) => setLabel(e.target.value.slice(0, 100))}
                  placeholder="e.g. Demo store backend"
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

              {errorText ? (
                <div
                  className="rounded-lg px-3 py-2 text-sm"
                  style={{
                    background: 'rgba(192,57,43,0.06)',
                    border: `1px solid ${DANGER}`,
                    color: INK,
                  }}
                >
                  {errorText}
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
                  }}
                >
                  Cancel
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
                  {submitting ? 'Creating…' : 'Create key'}
                </button>
              </div>
            </form>
          </>
        ) : (
          <>
            <h2 className="text-lg font-semibold m-0" style={{ color: DANGER }}>
              Copy your key now
            </h2>
            <div
              className="rounded-lg px-3 py-3 text-sm mt-4"
              style={{
                background: 'rgba(192,57,43,0.06)',
                border: `1px solid ${DANGER}`,
                color: INK,
              }}
            >
              This is the only time the full key is shown. Store it somewhere
              safe — it cannot be retrieved again.
            </div>
            <div className="mt-4">
              <label
                className="block text-xs font-medium mb-1"
                style={{ color: MUTED }}
              >
                {result?.label}
              </label>
              <pre
                className="w-full text-xs rounded-lg px-3 py-3 font-mono break-all whitespace-pre-wrap m-0"
                style={{
                  color: INK,
                  background: 'rgba(44,44,42,0.04)',
                  border: '1px solid rgba(136,135,128,0.25)',
                }}
              >
                {result?.key}
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
                  {copied ? 'Copied!' : 'Copy'}
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
              <span>I saved the key somewhere safe.</span>
            </label>
            <div className="flex items-center justify-end mt-4">
              <button
                type="button"
                onClick={() => {
                  onCreated?.()
                  onClose()
                }}
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
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
