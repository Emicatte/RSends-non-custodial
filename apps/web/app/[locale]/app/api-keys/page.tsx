'use client'

import { ApiKeysSettings } from '@/components/settings/ApiKeysSettings'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  accent: '#C45A3C',
  white: '#ffffff',
  border: '#e5e4e0',
  amber: '#D97A2E',
  amberLight: 'rgba(217, 122, 46, 0.08)',
}

/**
 * Phase E — API keys under `/app` (OQ-E3 = A).
 *
 * Mounts the existing session `rsusr_` CRUD (`ApiKeysSettings`) and surfaces the
 * honest interop gap: `rsusr_` user keys authenticate the dashboard/session APIs
 * but do NOT call the merchant payment API — those `rsend_` keys are minted with
 * wallet authentication in the Merchant Dashboard. The gap is logged here in-UI
 * (not hidden); session-authed `rsend_` management remains out of scope
 * (OQ-E3 Options B/C would touch the auth perimeter).
 */
export default function AppApiKeysPage() {
  return (
    <main className="rp-app-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Interop gap note — rsusr_ vs rsend_ */}
      <div
        style={{
          background: COLORS.amberLight,
          border: `1px solid ${COLORS.amber}`,
          borderRadius: 12,
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}
      >
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 700, color: COLORS.amber }}>
          Two key systems — know which you need
        </div>
        <p style={{ fontFamily: 'var(--font-display)', fontSize: 12.5, color: COLORS.ink, margin: 0, lineHeight: 1.5 }}>
          The keys below are <strong>user API keys</strong> (<code>rsusr_</code>) — they authenticate
          this dashboard&rsquo;s session APIs. They do <strong>not</strong> call the merchant payment API.
          To mint a <strong>merchant API key</strong> (<code>rsend_</code>) that creates payment intents,
          use the wallet-authenticated{' '}
          <a href="/merchant/dashboard" style={{ color: COLORS.accent, fontWeight: 600 }}>
            Merchant Dashboard
          </a>
          .
        </p>
      </div>

      <ApiKeysSettings />
    </main>
  )
}
