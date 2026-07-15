'use client'

import { ApiKeysSettings } from '@/components/settings/ApiKeysSettings'
import { MerchantApiKeys } from '@/components/settings/MerchantApiKeys'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
}

/**
 * API keys under `/app`.
 *
 * Two sections, honestly labeled:
 *   1. Merchant API keys (`rsend_test_`) — session-minted (Option B,
 *      2026-07-15), the REAL payment-API keys. Replaces the OQ-E3 interop
 *      banner that pointed at the wallet-authenticated Merchant Dashboard
 *      (which could not mint keys at all).
 *   2. Dashboard keys (`rsusr_`) — the pre-existing session CRUD, kept as-is.
 */
export default function AppApiKeysPage() {
  return (
    <main className="rp-app-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <MerchantApiKeys />

      <div>
        <h2 className="text-sm font-semibold m-0" style={{ color: COLORS.ink }}>
          Dashboard keys <code className="text-xs">rsusr_</code>
        </h2>
        <p className="text-xs mt-1 mb-3" style={{ color: COLORS.muted }}>
          Programmatic access to this dashboard&rsquo;s own APIs. These do{' '}
          <strong>not</strong> call the merchant payment API — use a merchant
          key above for that.
        </p>
        <ApiKeysSettings />
      </div>
    </main>
  )
}
