'use client'

import { useState } from 'react'
import { appPage, card } from '@/components/app/pageStyles'
// Moved to components/app so the marketing landing page can render the SAME
// card the merchant sees. Verbatim move; no behaviour change.
import { WebhookCard } from '@/components/app/WebhookCard'
import { useOrgWebhooks } from '@/hooks/useOrgWebhooks'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  accent: '#C45A3C',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.08)',
  blue: '#0052ff',
  blueLight: 'rgba(0, 82, 255, 0.08)',
}

// Mirror of the backend VALID_EVENTS (merchant_models.py) — the three event
// lists (backend allowlist, this picker, /docs/webhooks table) must agree.
const EVENT_OPTIONS = [
  'payment.completed',
  'payment.completed_late',
  'payment.expired',
  'payment.expired_rejected',
  'payment.needs_review',
  'payment.partial',
  'payment.overpaid',
  'payment.reversed',
  'payment.cancelled', // reserved: subscribable, not yet emitted
  'payment.ambiguous', // reserved: subscribable, not yet emitted
] as const

export default function WebhooksPage() {
  const { webhooks, loading, error, isAuthed, register, fetchDeliveries, sendTest, reEnable } = useOrgWebhooks()

  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>(['payment.completed'])
  const [submitting, setSubmitting] = useState(false)
  const [formErr, setFormErr] = useState<string | null>(null)
  const [newSecret, setNewSecret] = useState<string | null>(null)

  function toggleEvent(e: string) {
    setEvents((prev) => (prev.includes(e) ? prev.filter((x) => x !== e) : [...prev, e]))
  }

  async function onRegister(ev: React.FormEvent) {
    ev.preventDefault()
    setFormErr(null)
    setNewSecret(null)
    if (!url.startsWith('https://')) {
      setFormErr('Webhook URL must use HTTPS.')
      return
    }
    if (events.length === 0) {
      setFormErr('Select at least one event.')
      return
    }
    setSubmitting(true)
    try {
      const res = await register(url, events)
      setNewSecret(res.secret)
      setUrl('')
      setEvents(['payment.completed'])
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : 'Registration failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className={`${appPage} space-y-8`}>
      {/* Title lives in the topbar; the page opens with its one-line intro. */}
      <p className="m-0" style={{ fontFamily: 'var(--font-display)', fontSize: 13, color: COLORS.muted }}>
        Register endpoints and monitor delivery health. Testnet only.
      </p>

      {/* Register form */}
      <form onSubmit={onRegister} className={`${card} flex flex-col gap-4`}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 700, color: COLORS.ink }}>
          Register a webhook
        </div>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-server.example/webhooks/rsends"
          className="px-3 py-2.5 rounded-lg"
          style={{
            border: `1px solid ${COLORS.border}`,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
          }}
        />
        <div className="flex flex-wrap gap-2.5">
          {EVENT_OPTIONS.map((e) => (
            <label key={e} className="flex items-center gap-1.5" style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.ink, cursor: 'pointer' }}>
              <input type="checkbox" checked={events.includes(e)} onChange={() => toggleEvent(e)} />
              {e}
            </label>
          ))}
        </div>
        {formErr && <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.red }}>{formErr}</div>}
        <button
          type="submit"
          disabled={submitting}
          className="self-start px-4 py-2 rounded-lg"
          style={{
            border: 'none',
            background: COLORS.accent,
            color: COLORS.white,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            fontWeight: 600,
            cursor: submitting ? 'not-allowed' : 'pointer',
            opacity: submitting ? 0.6 : 1,
          }}
        >
          {submitting ? 'Registering…' : 'Register webhook'}
        </button>
        {newSecret && (
          <div className="px-4 py-3 rounded-lg" style={{ background: COLORS.orangeLight, border: `1px solid ${COLORS.orange}` }}>
            <div className="mb-1.5" style={{ fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 700, color: COLORS.orange }}>
              Save this signing secret — it is shown only once.
            </div>
            <code style={{ fontSize: 12, wordBreak: 'break-all', color: COLORS.ink }}>{newSecret}</code>
          </div>
        )}
      </form>

      {/* Endpoint list */}
      {!isAuthed ? (
        <div className={card} style={{ color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          Sign in to manage webhooks.
        </div>
      ) : loading ? (
        <div className={card} style={{ color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>Loading…</div>
      ) : error ? (
        <div className={card} style={{ color: COLORS.red, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          Couldn’t load webhooks ({error}).
        </div>
      ) : webhooks.length === 0 ? (
        <div className={card} style={{ color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          No webhooks registered yet.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {webhooks.map((w) => (
            <WebhookCard key={w.webhook_id} webhook={w} fetchDeliveries={fetchDeliveries} sendTest={sendTest} reEnable={reEnable} />
          ))}
        </div>
      )}
    </main>
  )
}
