/**
 * The /app home page — "we could not value these payments" disclosure.
 *
 * The backend excludes settlements in tokens with no USD peg from `volume_24h`
 * and from the volume-trend buckets, and reports how many it left out. If the
 * page renders the aggregate without that count, a merchant paid 2 ETH sees
 * "$0" — the same thing a merchant paid nothing sees. These tests pin the
 * disclosure: shown when there is something to disclose, absent when there
 * isn't (a zero count must not produce a permanent apologetic banner).
 *
 * next-intl is mocked with a FORMATTING stub rather than the usual
 * key→raw-string one, because the plural form and the `{symbols}`
 * interpolation are part of what is being asserted — a stub that returned the
 * raw ICU source would let "1 payments" through. `intl-messageformat` itself is
 * ESM-only and jest does not transform node_modules, so the two constructs
 * these messages actually use are formatted here instead of pulling in a
 * transform config this branch has no business changing.
 */
import { render, screen, waitFor } from '@testing-library/react'

/** `{name}` and `{count, plural, =1 {…} other {…}}` with `#`. Nothing else. */
function formatIcu(message: string, values: Record<string, unknown> = {}): string {
  const count = Number(values.count)
  const withPlurals = message.replace(
    /\{count,\s*plural,\s*=1\s*\{([^{}]*)\}\s*other\s*\{([^{}]*)\}\s*\}/g,
    (_m, one: string, other: string) =>
      (count === 1 ? one : other).replace(/#/g, String(count)),
  )
  return withPlurals.replace(/\{(\w+)\}/g, (m, key: string) =>
    key in values ? String(values[key]) : m,
  )
}

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    return (key: string, values?: Record<string, unknown>) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return formatIcu(value, values ?? {})
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok' },
    status: 'authenticated',
  }),
}))

import AppDashboardPage from '@/app/[locale]/app/page'

function statsPayload(overrides: Record<string, unknown> = {}) {
  return {
    volume_24h: 0,
    volume_24h_delta_pct: 0,
    transactions_24h: 0,
    transactions_24h_delta: 0,
    total_balance: 0,
    total_balance_chains: 0,
    active_clients: 0,
    active_clients_this_week: 0,
    recent_transactions: [],
    volume_24h_unpriced_count: 0,
    volume_24h_unpriced_symbols: [],
    settlement_wallet_set: true,
    has_api_key: true,
    has_paid_payment: true,
    ...overrides,
  }
}

function seriesPayload(overrides: Record<string, unknown> = {}) {
  return {
    days: 7,
    buckets: Array.from({ length: 7 }, (_, i) => ({
      date: `2026-03-0${i + 1}`,
      volume_usd: 0,
      unpriced_count: 0,
    })),
    unpriced_count: 0,
    ...overrides,
  }
}

/** Routes by URL: the page mounts useOrgStats AND useOrgVolumeSeries. */
function mockFetch(stats: unknown, series: unknown) {
  const fn = jest.fn(async (input: unknown) => {
    const url = String(input)
    const body = url.includes('volume-series') ? series : stats
    return { ok: true, status: 200, json: async () => body }
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

afterEach(() => {
  jest.resetAllMocks()
})

// ── the volume tile's disclosure ────────────────────────────────────────────

it('states the exclusion when the volume tile left payments out', async () => {
  mockFetch(
    statsPayload({
      transactions_24h: 2,
      volume_24h_unpriced_count: 2,
      volume_24h_unpriced_symbols: ['ETH'],
    }),
    seriesPayload(),
  )
  render(<AppDashboardPage />)

  const notice = await screen.findByTestId('volume-unpriced-notice')
  expect(notice.textContent).toContain('2 payments')
  expect(notice.textContent).toContain('ETH')
})

it('uses the singular and names the token for a single excluded payment', async () => {
  mockFetch(
    statsPayload({
      transactions_24h: 1,
      volume_24h_unpriced_count: 1,
      volume_24h_unpriced_symbols: ['ETH'],
    }),
    seriesPayload(),
  )
  render(<AppDashboardPage />)

  const notice = await screen.findByTestId('volume-unpriced-notice')
  expect(notice.textContent).toContain('1 payment')
  expect(notice.textContent).not.toContain('1 payments')
})

it('falls back to the token-less wording when the registry knows no symbol', async () => {
  mockFetch(
    statsPayload({
      transactions_24h: 1,
      volume_24h_unpriced_count: 1,
      volume_24h_unpriced_symbols: [],
    }),
    seriesPayload(),
  )
  render(<AppDashboardPage />)

  const notice = await screen.findByTestId('volume-unpriced-notice')
  expect(notice.textContent).toContain('1 payment')
})

it('shows no notice when nothing was excluded', async () => {
  mockFetch(statsPayload({ volume_24h: 1234, transactions_24h: 3 }), seriesPayload())
  render(<AppDashboardPage />)

  // Wait for the page to actually have data, so this is not a false pass on a
  // still-loading render.
  await screen.findByText('$1,234')
  expect(screen.queryByTestId('volume-unpriced-notice')).toBeNull()
})

// ── the chart's own disclosure (7d window, not the tile's 24h) ───────────────

it('states the chart exclusion separately from the tile', async () => {
  mockFetch(statsPayload(), seriesPayload({ unpriced_count: 4 }))
  render(<AppDashboardPage />)

  const notice = await screen.findByTestId('series-unpriced-notice')
  expect(notice.textContent).toContain('4 payments')
  // The tile's own window excluded nothing, so it must stay quiet.
  expect(screen.queryByTestId('volume-unpriced-notice')).toBeNull()
})

it('shows no chart notice when the window excluded nothing', async () => {
  mockFetch(statsPayload({ volume_24h: 500 }), seriesPayload())
  render(<AppDashboardPage />)

  await screen.findByText('$500')
  expect(screen.queryByTestId('series-unpriced-notice')).toBeNull()
})

// ── recent transactions: the same lie, one row at a time ────────────────────

it('names the token instead of "$0" for an unvaluable recent payment', async () => {
  mockFetch(
    statsPayload({
      transactions_24h: 1,
      volume_24h_unpriced_count: 1,
      volume_24h_unpriced_symbols: ['ETH'],
      recent_transactions: [
        {
          id: 1,
          tx_hash: '0xabc',
          type: 'transfer',
          amount_usd: 0,
          amount_usd_known: false,
          currency: 'ETH',
          chain: 'Base',
          status: 'confirmed',
          recipient: '0x' + 'd'.repeat(40),
          timestamp_iso: '2026-03-15T00:00:00+00:00',
        },
      ],
    }),
    seriesPayload(),
  )
  render(<AppDashboardPage />)

  const cell = await screen.findByText(/ETH — not valued/)
  // Scoped to the row, deliberately: the volume TILE does show "$0" here, and
  // that is correct — it is accompanied by the notice. What must never carry a
  // dollar figure is the row itself, where nothing would explain it.
  const row = cell.closest('tr') ?? cell.parentElement
  expect(row).not.toBeNull()
  expect(row!.textContent).not.toContain('$')
})

it('still renders a dollar amount for a valued recent payment', async () => {
  mockFetch(
    statsPayload({
      transactions_24h: 1,
      volume_24h: 5,
      recent_transactions: [
        {
          id: 1,
          tx_hash: '0xabc',
          type: 'transfer',
          amount_usd: 5,
          amount_usd_known: true,
          currency: 'USDC',
          chain: 'Base',
          status: 'confirmed',
          recipient: '0x' + 'd'.repeat(40),
          timestamp_iso: '2026-03-15T00:00:00+00:00',
        },
      ],
    }),
    seriesPayload(),
  )
  render(<AppDashboardPage />)

  await waitFor(() => expect(screen.getAllByText('$5').length).toBeGreaterThan(0))
})

// ── the copy itself has to survive in every shipped locale ──────────────────

it('keeps the exclusion copy usable in all five shipped locales', () => {
  // Not a full ICU parse — a formatting stub cannot be one. What it catches is
  // what actually breaks when copy is translated: a dropped placeholder, a
  // half-written plural block, or an unbalanced brace, any of which would ship
  // raw ICU source into the dashboard.
  const balanced = (m: string) =>
    m.split('{').length === m.split('}').length

  for (const locale of ['en', 'it', 'es', 'fr', 'de']) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const dash = require(`@/messages/${locale}.json`).app.dashboard
    const { volume, volumeTokens, series } = dash.unpriced

    for (const message of [volume, volumeTokens, series]) {
      expect(balanced(message)).toBe(true)
      expect(message).toContain('{count, plural,')
      expect(message).toContain('other {')
      // Both arms must actually substitute the number.
      expect(formatIcu(message, { count: 3, symbols: 'ETH' })).toContain('3')
      expect(formatIcu(message, { count: 1, symbols: 'ETH' })).toContain('1')
    }

    expect(volumeTokens).toContain('{symbols}')
    expect(formatIcu(volumeTokens, { count: 2, symbols: 'ETH' })).toContain('ETH')

    const row = dash.recentTransactions.amountUnpriced
    expect(row).toContain('{symbol}')
    expect(formatIcu(row, { symbol: 'ETH' })).toContain('ETH')
    // Never a bare currency-looking zero.
    expect(formatIcu(row, { symbol: 'ETH' })).not.toContain('$0')
  }
})
