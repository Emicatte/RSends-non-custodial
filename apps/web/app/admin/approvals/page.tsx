'use client'

/**
 * /admin/approvals — the merchant review queue. Locale-free admin shell
 * (protected by the admin_session cookie guard in middleware.ts, same as
 * /admin/transactions). Lists pending orgs with their full KYB profile;
 * approve / decline (with reason) act through the server-side bridge that
 * speaks X-Admin-Token to the backend. The DB is the source of truth — the
 * Telegram message is only a convenience pointer to this page.
 */

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

interface PendingRow {
  org_id: string
  name: string
  slug: string
  created_at: string | null
  approval_requested_at: string | null
  profile_submitted_at: string | null
  company_profile: Record<string, unknown>
}

const PROFILE_LABELS: Array<[string, string]> = [
  ['legal_name', 'Legal name'],
  ['trading_name', 'Trading name'],
  ['country', 'Country'],
  ['registration_number', 'Registration #'],
  ['tax_or_vat_number', 'Tax / VAT'],
  ['website', 'Website'],
  ['business_category', 'Category'],
  ['expected_monthly_volume', 'Expected volume'],
  ['countries_served', 'Countries served'],
  ['primary_stablecoin', 'Stablecoin'],
  ['no_sanctioned_countries', 'No sanctioned countries'],
  ['no_prohibited_activities', 'No prohibited activities'],
  ['has_pep', 'PEP'],
]

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

export default function AdminApprovalsPage() {
  const router = useRouter()
  const [rows, setRows] = useState<PendingRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  const fetchQueue = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      if (!opts.silent) setLoading(true)
      try {
        const res = await fetch('/api/admin/approvals', { cache: 'no-store' })
        if (res.status === 401) {
          router.push('/admin/login')
          return
        }
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as { error?: string }
          throw new Error(body.error ?? `HTTP ${res.status}`)
        }
        setRows((await res.json()) as PendingRow[])
        setError(null)
      } catch (e) {
        // Fail loud: a failed read must never leave a plausible-but-unverified
        // queue (or an empty-state that implies a successful read) on screen.
        setRows([])
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [router],
  )

  useEffect(() => {
    void fetchQueue()
    const timer = setInterval(() => void fetchQueue({ silent: true }), 30_000)
    return () => clearInterval(timer)
  }, [fetchQueue])

  const decide = useCallback(
    async (orgId: string, action: 'approve' | 'decline') => {
      let reason: string | undefined
      if (action === 'decline') {
        reason = window.prompt('Decline reason (shown to the merchant):')?.trim()
        if (!reason) return
      } else if (!window.confirm('Approve this merchant?')) {
        return
      }
      setActing(orgId)
      try {
        const res = await fetch(`/api/admin/approvals/${orgId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, reason }),
        })
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as {
            error?: string
            detail?: { code?: string }
          }
          throw new Error(body.detail?.code ?? body.error ?? `HTTP ${res.status}`)
        }
        await fetchQueue({ silent: true })
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setActing(null)
      }
    },
    [fetchQueue],
  )

  return (
    <div className="min-h-screen text-[#0A0A0A]" style={{ background: '#FAFAFA' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-8">
        <header className="mb-8 flex items-center gap-3">
          <span
            className="inline-flex h-10 w-10 items-center justify-center rounded-xl text-lg"
            style={{ background: '#C8512C', color: '#FFFFFF' }}
            aria-hidden
          >
            ✓
          </span>
          <div>
            <h1 className="text-xl font-semibold">Merchant approvals</h1>
            <p className="text-sm" style={{ color: '#55544E' }}>
              Pending KYB submissions — approve or decline. Auto-refreshes every 30s.
            </p>
          </div>
        </header>

        {/* Error is EXCLUSIVE: when the read failed, show only the error —
            never the empty-state or a stale list, which would imply a
            successful read of an empty queue. */}
        {error ? (
          <p role="alert" className="mb-4 text-sm" style={{ color: '#B3261E' }}>
            {error}
          </p>
        ) : loading ? (
          <p className="text-sm" style={{ color: '#888780' }}>
            Loading…
          </p>
        ) : rows.length === 0 ? (
          <p className="text-sm" style={{ color: '#888780' }}>
            Queue is empty — no merchants waiting for review.
          </p>
        ) : (
          <div className="space-y-6">
            {rows.map((row) => (
              <section
                key={row.org_id}
                className="rounded-xl border p-5"
                style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
              >
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">{row.name}</h2>
                    <p className="text-xs" style={{ color: '#888780' }}>
                      {row.slug} · submitted{' '}
                      {row.profile_submitted_at
                        ? new Date(row.profile_submitted_at).toLocaleString()
                        : '—'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={acting === row.org_id}
                      onClick={() => void decide(row.org_id, 'approve')}
                      className="rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
                      style={{ background: '#1B7F4B', color: '#FFFFFF' }}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      disabled={acting === row.org_id}
                      onClick={() => void decide(row.org_id, 'decline')}
                      className="rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
                      style={{ background: '#B3261E', color: '#FFFFFF' }}
                    >
                      Decline
                    </button>
                  </div>
                </div>
                <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm md:grid-cols-2">
                  {PROFILE_LABELS.map(([key, label]) => (
                    <div key={key} className="flex justify-between gap-4">
                      <dt style={{ color: '#888780' }}>{label}</dt>
                      <dd className="text-right font-medium">
                        {fmt(row.company_profile?.[key])}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
