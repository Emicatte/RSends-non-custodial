'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  useOrgWebhooks,
  type OrgWebhook,
  type OrgWebhookDelivery,
} from '@/hooks/useOrgWebhooks'

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

// Subset of the backend VALID_EVENTS most merchants subscribe to.
const EVENT_OPTIONS = [
  'payment.completed',
  'payment.expired',
  'payment.cancelled',
  'payment.partial',
  'payment.overpaid',
] as const

const card: React.CSSProperties = {
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 12,
  padding: '18px 20px',
}

const badge = (bg: string, text: string): React.CSSProperties => ({
  display: 'inline-block',
  padding: '3px 8px',
  borderRadius: 6,
  background: bg,
  color: text,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.02em',
})

function withinDay(iso: string, nowMs: number): boolean {
  const t = new Date(iso).getTime()
  return Number.isFinite(t) && nowMs - t <= 86_400_000
}

function WebhookCard({
  webhook,
  fetchDeliveries,
  sendTest,
}: {
  webhook: OrgWebhook
  fetchDeliveries: (id: number) => Promise<OrgWebhookDelivery[]>
  sendTest: (id: number) => Promise<{ status: string; response_code: number | null; message: string }>
}) {
  const [deliveries, setDeliveries] = useState<OrgWebhookDelivery[] | null>(null)
  const [testing, setTesting] = useState(false)
  const [testMsg, setTestMsg] = useState<string | null>(null)

  const loadDeliveries = useCallback(async () => {
    try {
      setDeliveries(await fetchDeliveries(webhook.webhook_id))
    } catch {
      setDeliveries([])
    }
  }, [fetchDeliveries, webhook.webhook_id])

  useEffect(() => {
    void loadDeliveries()
  }, [loadDeliveries])

  const nowMs = Date.now()
  const delivered24h = (deliveries ?? []).filter(
    (d) => d.status === 'delivered' && withinDay(d.created_at, nowMs),
  ).length
  const failed24h = (deliveries ?? []).filter(
    (d) => d.status === 'failed' && withinDay(d.created_at, nowMs),
  ).length
  const pendingRetries = (deliveries ?? []).filter(
    (d) => d.status === 'pending',
  ).length
  const last = (deliveries ?? [])[0]

  async function onTest() {
    setTesting(true)
    setTestMsg(null)
    try {
      const res = await sendTest(webhook.webhook_id)
      setTestMsg(
        res.status === 'ok'
          ? `Test delivered (HTTP ${res.response_code ?? '—'})`
          : `Test failed: ${res.message}`,
      )
      await loadDeliveries()
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : 'Test failed')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 700, color: COLORS.ink, wordBreak: 'break-all' }}>
            {webhook.url}
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <span style={badge(COLORS.blueLight, COLORS.blue)}>TEST</span>
            <span style={badge(webhook.is_active ? COLORS.greenLight : COLORS.redLight, webhook.is_active ? COLORS.green : COLORS.red)}>
              {webhook.is_active ? 'ACTIVE' : 'INACTIVE'}
            </span>
            {webhook.events.map((e) => (
              <span key={e} style={badge(COLORS.paper, COLORS.muted)}>{e}</span>
            ))}
          </div>
        </div>
        <button
          onClick={onTest}
          disabled={testing || !webhook.is_active}
          style={{
            flexShrink: 0,
            padding: '8px 14px',
            borderRadius: 8,
            border: 'none',
            background: COLORS.accent,
            color: COLORS.white,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            fontWeight: 600,
            cursor: testing || !webhook.is_active ? 'not-allowed' : 'pointer',
            opacity: testing || !webhook.is_active ? 0.6 : 1,
          }}
        >
          {testing ? 'Sending…' : 'Send test'}
        </button>
      </div>

      {/* Health row */}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontFamily: 'var(--font-display)', fontSize: 12 }}>
        <Health label="Delivered (24h)" value={String(delivered24h)} color={COLORS.green} />
        <Health label="Failed (24h)" value={String(failed24h)} color={failed24h > 0 ? COLORS.red : COLORS.muted} />
        <Health label="Pending retries" value={String(pendingRetries)} color={pendingRetries > 0 ? COLORS.orange : COLORS.muted} />
        <Health
          label="Last delivery"
          value={last ? `${last.status}${last.response_code ? ` · ${last.response_code}` : ''}` : '—'}
          color={COLORS.ink}
        />
      </div>

      {testMsg && (
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.muted }}>{testMsg}</div>
      )}
    </div>
  )
}

function Health({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: COLORS.muted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </div>
      <div style={{ fontSize: 15, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

export default function WebhooksPage() {
  const { webhooks, loading, error, isAuthed, register, fetchDeliveries, sendTest } = useOrgWebhooks()

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
    <main className="rp-app-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 700, color: COLORS.ink, margin: 0 }}>
          Webhooks
        </h1>
        <p style={{ fontFamily: 'var(--font-display)', fontSize: 13, color: COLORS.muted, margin: '4px 0 0' }}>
          Register endpoints and monitor delivery health. Testnet only.
        </p>
      </div>

      {/* Register form */}
      <form onSubmit={onRegister} style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 700, color: COLORS.ink }}>
          Register a webhook
        </div>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-server.example/webhooks/rsends"
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: `1px solid ${COLORS.border}`,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
          }}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {EVENT_OPTIONS.map((e) => (
            <label key={e} style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.ink, cursor: 'pointer' }}>
              <input type="checkbox" checked={events.includes(e)} onChange={() => toggleEvent(e)} />
              {e}
            </label>
          ))}
        </div>
        {formErr && <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.red }}>{formErr}</div>}
        <button
          type="submit"
          disabled={submitting}
          style={{
            alignSelf: 'flex-start',
            padding: '9px 16px',
            borderRadius: 8,
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
          <div style={{ background: COLORS.orangeLight, border: `1px solid ${COLORS.orange}`, borderRadius: 8, padding: '12px 14px' }}>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 700, color: COLORS.orange, marginBottom: 6 }}>
              Save this signing secret — it is shown only once.
            </div>
            <code style={{ fontSize: 12, wordBreak: 'break-all', color: COLORS.ink }}>{newSecret}</code>
          </div>
        )}
      </form>

      {/* Endpoint list */}
      {!isAuthed ? (
        <div style={{ ...card, color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          Sign in to manage webhooks.
        </div>
      ) : loading ? (
        <div style={{ ...card, color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>Loading…</div>
      ) : error ? (
        <div style={{ ...card, color: COLORS.red, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          Couldn’t load webhooks ({error}).
        </div>
      ) : webhooks.length === 0 ? (
        <div style={{ ...card, color: COLORS.muted, fontFamily: 'var(--font-display)', fontSize: 13 }}>
          No webhooks registered yet.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {webhooks.map((w) => (
            <WebhookCard key={w.webhook_id} webhook={w} fetchDeliveries={fetchDeliveries} sendTest={sendTest} />
          ))}
        </div>
      )}
    </main>
  )
}
