'use client'

/**
 * "Get started" checklist card for the /app home — DERIVED state, fed by the
 * org-stats checklist booleans (settlement_wallet_set / has_api_key /
 * has_paid_payment). Links to EXISTING surfaces only: settlement wallet
 * config (settings/organization, Phase B), the API keys tab (Phase E), and
 * creating a test payment (/app/payments).
 *
 * Render contract (no persistence — the card is a function of state):
 *  - `loading`   → skeleton reserving the final layout (never flash an item
 *                  as incomplete before the data lands);
 *  - no data     → nothing (error state; don't show a wrong checklist);
 *  - all done    → nothing (the card removes itself, no dismissal flag);
 *  - otherwise   → incomplete items as numbered links, completed items kept
 *                  in place but muted, checked, non-actionable (sr "Completed").
 */

import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

export interface ChecklistCompletion {
  wallet: boolean
  apiKey: boolean
  testPayment: boolean
}

export interface GetStartedChecklistProps {
  /** The page passes its stats-loading predicate (`loading && !stats`). */
  loading: boolean
  /** null after load = no data (error) → render nothing. */
  completed: ChecklistCompletion | null
}

const ITEMS = [
  { key: 'wallet', href: '/settings/organization' },
  { key: 'apiKey', href: '/app/api-keys' },
  { key: 'testPayment', href: '/app/payments' },
] as const

// Visually hidden, but immediately available to screen readers (same inline
// pattern as TypewriterHeadline — the project defines no sr-only utility).
const SR_ONLY: React.CSSProperties = {
  position: 'absolute',
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
}

export function GetStartedChecklist({
  loading,
  completed,
}: GetStartedChecklistProps) {
  const t = useTranslations('onboarding.checklist')

  if (loading) {
    return (
      <div
        className="rounded-xl border p-5"
        style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
        data-testid="get-started-skeleton"
        aria-hidden="true"
      >
        {/* h-5 matches the card's text-sm h2 line height exactly */}
        <div
          className="mb-4 h-5 w-1/4 rounded-lg"
          style={{
            background: '#e5e4e0',
            animation: 'rsendsPulse 1.5s ease-in-out infinite',
          }}
        />
        <div className="space-y-2">
          {ITEMS.map((item) => (
            <div
              key={item.key}
              className="h-10 rounded-lg"
              style={{
                background: '#e5e4e0',
                animation: 'rsendsPulse 1.5s ease-in-out infinite',
              }}
            />
          ))}
        </div>
      </div>
    )
  }

  if (!completed) return null
  if (completed.wallet && completed.apiKey && completed.testPayment) {
    return null
  }

  return (
    <div
      className="rounded-xl border p-5"
      style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
    >
      <h2 className="text-sm font-semibold mb-4" style={{ color: '#0A0A0A' }}>
        {t('title')}
      </h2>
      <ul className="space-y-2">
        {ITEMS.map((item, i) => (
          <li key={item.key}>
            {completed[item.key] ? (
              // #6b6b6b (the page's muted tone) keeps WCAG AA contrast on
              // white; the check circle stays lighter as it's decorative.
              <div
                className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm"
                style={{ borderColor: '#DDDCD6', color: '#6b6b6b' }}
              >
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px]"
                  style={{ borderColor: '#9a9a9a', color: '#9a9a9a' }}
                  aria-hidden="true"
                >
                  ✓
                </span>
                {t(item.key)}
                <span style={SR_ONLY}>{t('completed')}</span>
              </div>
            ) : (
              <Link
                href={item.href}
                className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm hover:border-[#C8512C]"
                style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
              >
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px]"
                  style={{ borderColor: '#C8512C', color: '#C8512C' }}
                >
                  {i + 1}
                </span>
                {t(item.key)}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
