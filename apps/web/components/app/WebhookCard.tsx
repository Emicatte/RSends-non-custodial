'use client'

import { useCallback, useEffect, useState } from 'react'
import { card } from '@/components/app/pageStyles'
import { useClientNow } from '@/hooks/useClientNow'
import type { OrgWebhook, OrgWebhookDelivery } from '@/hooks/useOrgWebhooks'

/**
 * One webhook endpoint with its delivery health, lifted verbatim out of
 * app/[locale]/app/webhooks/page.tsx. Same reason as PaymentsTable and
 * MetricCards: the marketing landing page renders the real card against a
 * fixture rather than a screenshot of it.
 *
 * It loads its own deliveries through the `fetchDeliveries` prop, so a caller
 * with no backend supplies `async () => [...]` and needs nothing else.
 *
 * KNOWN GAP, moved unchanged: this card is the one dashboard surface with NO
 * i18n — "Send test", "Delivered (24h)", "Failed (24h)", "Pending retries",
 * "Last delivery", ACTIVE/INACTIVE and TEST are hardcoded English, while the
 * payments table and the KPI cards beside it are fully translated. Localizing
 * it is a behaviour change and belongs to its own pass; this move deliberately
 * does not make it, so the extraction stays reviewable as a pure move.
 */

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

// Spacing lives in badgeClass; the helper keeps only the tone.
const badgeClass = 'inline-block px-2 py-0.5 rounded-md'
const badge = (bg: string, text: string): React.CSSProperties => ({
  background: bg,
  color: text,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.02em',
})

// `nowMs === null` before mount (see useClientNow): with no clock there is no
// 24h window to test, so nothing counts. `deliveries` is null on those passes
// anyway, so the counters read 0 either way — this just keeps the server and
// the first client render agreeing by construction rather than by luck.
function withinDay(iso: string, nowMs: number | null): boolean {
  if (nowMs === null) return false
  const t = new Date(iso).getTime()
  return Number.isFinite(t) && nowMs - t <= 86_400_000
}

/**
 * The copy for a `disabled_reason` CODE. The backend stores codes precisely so
 * this mapping can change without touching rows.
 *
 * The `url_not_allowed:` family is worded to say the URL is unreachable BY
 * POLICY — we declined to contact it — rather than implying the merchant's
 * server misbehaved, because in that case it was never contacted at all.
 */
function disabledReasonText(code: string | null): string {
  if (!code) return 'This endpoint was disabled.'
  if (code.startsWith('url_not_allowed:')) {
    return 'This URL is not an allowed destination, so we never contacted it. It must be a public HTTPS address.'
  }
  switch (code) {
    case 'endpoint_not_found_404':
      return 'The endpoint answered 404 (not found) on three consecutive deliveries.'
    case 'endpoint_gone_410':
      return 'The endpoint answered 410 (gone) on three consecutive deliveries.'
    case 'dns_resolution_failed':
      return "The URL's hostname could not be resolved on three consecutive deliveries."
    default:
      return 'This endpoint failed permanently on three consecutive deliveries.'
  }
}

// Date only, UTC-pinned: the same reason useClientNow exists — a locale- or
// timezone-derived string differs between server and client and breaks
// hydration. See i18n/request.ts, which pins timeZone: 'UTC'.
function disabledOnText(iso: string | null): string {
  if (!iso) return ''
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ''
  return ` Disabled on ${t.toISOString().slice(0, 10)}.`
}

export function WebhookCard({
  webhook,
  fetchDeliveries,
  sendTest,
  reEnable,
}: {
  webhook: OrgWebhook
  fetchDeliveries: (id: number) => Promise<OrgWebhookDelivery[]>
  sendTest: (id: number) => Promise<{ status: string; response_code: number | null; message: string }>
  /** Omitted by callers with no backend (the landing-page fixture), which just
   *  hides the button — the disabled banner still renders. */
  reEnable?: (id: number) => Promise<unknown>
}) {
  const [deliveries, setDeliveries] = useState<OrgWebhookDelivery[] | null>(null)
  const [testing, setTesting] = useState(false)
  const [testMsg, setTestMsg] = useState<string | null>(null)
  const [enabling, setEnabling] = useState(false)
  const [enableErr, setEnableErr] = useState<string | null>(null)

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

  // Never `Date.now()` in the render body — see useClientNow.
  const nowMs = useClientNow()
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

  async function onReEnable() {
    if (!reEnable) return
    setEnabling(true)
    setEnableErr(null)
    try {
      await reEnable(webhook.webhook_id)
    } catch (e) {
      setEnableErr(e instanceof Error ? e.message : 'Could not re-enable')
    } finally {
      setEnabling(false)
    }
  }

  return (
    <div className={`${card} flex flex-col gap-3`}>
      <div className="flex items-center justify-between gap-3">
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 700, color: COLORS.ink, wordBreak: 'break-all' }}>
            {webhook.url}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <span className={badgeClass} style={badge(COLORS.blueLight, COLORS.blue)}>TEST</span>
            <span className={badgeClass} style={badge(webhook.is_active ? COLORS.greenLight : COLORS.redLight, webhook.is_active ? COLORS.green : COLORS.red)}>
              {/* AUTO-DISABLED reads differently from INACTIVE: one is
                  something the system did to them, the other is just a state. */}
              {webhook.is_active ? 'ACTIVE' : webhook.disabled_at ? 'AUTO-DISABLED' : 'INACTIVE'}
            </span>
            {webhook.events.map((e) => (
              <span key={e} className={badgeClass} style={badge(COLORS.paper, COLORS.muted)}>{e}</span>
            ))}
          </div>
        </div>
        <button
          onClick={onTest}
          disabled={testing || !webhook.is_active}
          className="px-3.5 py-2 rounded-lg"
          style={{
            flexShrink: 0,
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

      {/* Why it stopped. Without this the merchant sees notifications end with
          no date and no cause — a silent failure, which is worse than the noisy
          one auto-disable removed. */}
      {!webhook.is_active && webhook.disabled_at && (
        <div
          className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 rounded-lg"
          style={{ background: COLORS.redLight, fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.ink }}
        >
          <span style={{ minWidth: 0 }}>
            {disabledReasonText(webhook.disabled_reason)}
            {disabledOnText(webhook.disabled_at)}
            {' No further events are being sent to it.'}
          </span>
          {reEnable && (
            <button
              onClick={onReEnable}
              disabled={enabling}
              className="px-3 py-1.5 rounded-lg"
              style={{
                flexShrink: 0,
                border: `1px solid ${COLORS.red}`,
                background: 'transparent',
                color: COLORS.red,
                fontFamily: 'var(--font-display)',
                fontSize: 12,
                fontWeight: 600,
                cursor: enabling ? 'not-allowed' : 'pointer',
                opacity: enabling ? 0.6 : 1,
              }}
            >
              {enabling ? 'Re-enabling…' : 'Re-enable'}
            </button>
          )}
        </div>
      )}

      {enableErr && (
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: COLORS.red }}>{enableErr}</div>
      )}

      {/* Health row */}
      <div className="flex flex-wrap gap-5" style={{ fontFamily: 'var(--font-display)', fontSize: 12 }}>
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

