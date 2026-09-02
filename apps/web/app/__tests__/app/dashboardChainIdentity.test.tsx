/**
 * The /app home's chain column — what it says the network is.
 *
 * The page used to run every backend chain value through a three-entry
 * whitelist and coerce anything outside it to the literal 'Base':
 *
 *     chain: FE_CHAINS.includes(r.chain) ? r.chain : 'Base'
 *
 * The backend can emit seven different values there and exactly ONE of them
 * ("Base") was in that whitelist, so six were rewritten. The two the whitelist
 * held beyond it, 'Tron' and 'Sol', were strings the backend cannot produce.
 *
 * The consequence was not limited to TRON. `/app` is hard-locked to the `test`
 * environment, so essentially every settlement it shows is Base Sepolia — and
 * every one of them was presented as Base MAINNET. That is the defect these
 * tests exist for; TRON is the loud instance of it, not the whole of it.
 *
 * The fix is that the row carries a machine-stable `chain_key` and the display
 * text is derived from it through ONE helper, so a badge lookup and an explorer
 * lookup can no longer be keyed on two different vocabularies.
 */
import { render, screen, waitFor, within } from '@testing-library/react'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .reduce((node: any, part: string) => node?.[part], messages)
    return (key: string) => {
      const value = key
        .split('.')
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({ data: { access_token: 'tok' }, status: 'authenticated' }),
}))

import AppDashboardPage from '@/app/[locale]/app/page'
import { explorerTxUrl } from '@/lib/web3/explorer'
import { CHAIN_LABELS } from '@/lib/web3/paymentIntent'

const tx = (chain_key: string, id = 1) => ({
  id,
  tx_hash: '0x' + 'a'.repeat(64),
  type: 'transfer',
  amount_usd: 1240,
  currency: 'USDC',
  chain_key,
  status: 'confirmed',
  recipient: '0x1234…abcd',
  timestamp_iso: '2026-03-15T10:00:00Z',
  amount_usd_known: true,
})

function statsPayload(recent: ReturnType<typeof tx>[]) {
  return {
    volume_24h: 1240,
    volume_24h_delta_pct: 0,
    transactions_24h: recent.length,
    transactions_24h_delta: 0,
    total_balance: 0,
    total_balance_chains: 1,
    active_clients: 0,
    active_clients_this_week: 0,
    recent_transactions: recent,
    volume_24h_unpriced_count: 0,
    volume_24h_unpriced_symbols: [],
    settlement_wallet_set: true,
    has_api_key: true,
    has_paid_payment: true,
  }
}

const seriesPayload = {
  days: 7,
  buckets: Array.from({ length: 7 }, (_, i) => ({
    date: `2026-03-0${i + 1}`,
    volume_usd: 0,
    unpriced_count: 0,
  })),
  unpriced_count: 0,
}

function mockFetch(stats: unknown) {
  global.fetch = jest.fn(async (input: unknown) => {
    const url = String(input)
    return {
      ok: true,
      status: 200,
      json: async () => (url.includes('volume-series') ? seriesPayload : stats),
    }
  }) as unknown as typeof fetch
}

afterEach(() => jest.resetAllMocks())

/** The first data row of the recent-settlements table, once it has one. */
async function firstDataRow(): Promise<HTMLElement> {
  const table = await screen.findByRole('table')
  return waitFor(() => {
    // The rows arrive from the stats poll, so the table exists before its body
    // does; without this the assertion races the fetch.
    const rows = within(table).getAllByRole('row')
    if (rows.length < 2) throw new Error('no data rows yet')
    return rows[1] as HTMLElement
  })
}

/** The chain cell's badge in the first data row. */
async function chainBadge(): Promise<HTMLElement> {
  const row = await firstDataRow()
  const cell = within(row).getAllByRole('cell')[3]
  const badge = cell.querySelector('span')
  if (!badge) throw new Error('no chain badge rendered')
  return badge as HTMLElement
}

// ── it says which network, and testnet is not mainnet ───────────────────────

it('shows Base Sepolia as Base Sepolia, not as Base', async () => {
  mockFetch(statsPayload([tx('base_sepolia')]))
  render(<AppDashboardPage />)

  const badge = await chainBadge()
  expect(badge.textContent).toBe('Base Sepolia')
  expect(badge.textContent).not.toBe('Base')
})

it('gives a testnet a different label AND a different badge from its mainnet', async () => {
  mockFetch(statsPayload([tx('base_sepolia')]))
  const { unmount } = render(<AppDashboardPage />)
  const sepolia = await chainBadge()
  const sepoliaLook = {
    text: sepolia.textContent,
    bg: sepolia.style.background,
    border: sepolia.style.border,
  }
  unmount()

  mockFetch(statsPayload([tx('base')]))
  render(<AppDashboardPage />)
  const mainnet = await chainBadge()

  // Two nearly identical words are not enough to tell a testnet payment from a
  // mainnet one at a glance, so the badge itself must differ too.
  expect(sepoliaLook.text).not.toBe(mainnet.textContent)
  expect([sepoliaLook.bg, sepoliaLook.border]).not.toEqual([
    mainnet.style.background,
    mainnet.style.border,
  ])
})

it.each([
  ['ethereum', 'Ethereum'],
  ['arbitrum', 'Arbitrum'],
  ['tron_nile', 'TRON Nile'],
  ['tron', 'TRON'],
])('renders %s as its own network, never as Base', async (key, label) => {
  mockFetch(statsPayload([tx(key)]))
  render(<AppDashboardPage />)

  const badge = await chainBadge()
  expect(badge.textContent).toBe(label)
})

it('never prints "Base" anywhere in a non-Base row', async () => {
  // The generalisation guard. Asserted on the ROW, not the page: the dashboard
  // has other legitimate copy, and "Base Sepolia" legitimately contains "Base"
  // as a substring — which is why this case uses TRON, where the substring must
  // not occur at all.
  mockFetch(statsPayload([tx('tron_nile')]))
  render(<AppDashboardPage />)

  const row = await firstDataRow()
  expect(row.textContent).not.toContain('Base')
})

// ── an unidentified chain is shown as unidentified ──────────────────────────

it('renders an unrecognised chain key verbatim, in the neutral badge', async () => {
  mockFetch(statsPayload([tx('chain:999999')]))
  render(<AppDashboardPage />)

  const badge = await chainBadge()
  // The raw reference, exactly as the backend sent it. Not "Base", not blank,
  // not a guess.
  expect(badge.textContent).toBe('chain:999999')
})

it('does not paint an unrecognised chain in Base blue', async () => {
  mockFetch(statsPayload([tx('chain:999999')]))
  const { unmount } = render(<AppDashboardPage />)
  const unknown = await chainBadge()
  const unknownColor = unknown.style.color
  unmount()

  mockFetch(statsPayload([tx('base')]))
  render(<AppDashboardPage />)
  const base = await chainBadge()

  expect(unknownColor).not.toBe(base.style.color)
})

it('survives a backend that does not send chain_key yet', async () => {
  // Deploy skew, not a hypothetical: web ships on Vercel and the backend on
  // Render, independently, so a browser can hold a build that reads chain_key
  // while the API it is talking to predates it. The dashboard must degrade to
  // "we are not telling you the network" — never crash, and never fall back to
  // a chain we merely support.
  const { chain_key: _omitted, ...withoutKey } = tx('base_sepolia')
  mockFetch(statsPayload([withoutKey as ReturnType<typeof tx>]))
  render(<AppDashboardPage />)

  const badge = await chainBadge()
  expect(badge.textContent).toBe('')
  expect(badge.style.color).not.toBe('rgb(0, 82, 255)')
})

it('offers no explorer link for a chain it cannot identify', async () => {
  mockFetch(statsPayload([tx('chain:999999')]))
  render(<AppDashboardPage />)

  const row = await firstDataRow()
  expect(row.querySelector('a')).toBeNull()
})

// ── regression: the one chain that was right stays right ────────────────────

it('leaves Base mainnet rows exactly as they were', async () => {
  mockFetch(statsPayload([tx('base')]))
  render(<AppDashboardPage />)

  const badge = await chainBadge()
  expect(badge.textContent).toBe('Base')
  expect(badge.style.color).toBe('rgb(0, 82, 255)')
})

// ── the two vocabularies are now one ────────────────────────────────────────

describe('chain_key is the single vocabulary', () => {
  /** Every key `chain_display.build_chain_key_by_id` can produce, bar the
   *  `chain:{id}` fallback, which is deliberately unresolvable. */
  const BACKEND_KEYS = [
    'base',
    'base_sepolia',
    'ethereum',
    'arbitrum',
    'tron',
    'tron_nile',
  ]

  it('resolves every chain key the backend can emit to a label', () => {
    // PIN C. This is what makes adding a chain to the backend's assembled map
    // break the suite instead of silently rendering a raw snake key at a
    // merchant.
    for (const key of BACKEND_KEYS) {
      expect(CHAIN_LABELS[key.toUpperCase()]).toBeTruthy()
    }
  })

  it('sends each chain key to its own explorer, and only base to basescan', () => {
    // explorer.ts was already keyed on snake names; the badge was keyed on
    // labels. Now both read chain_key, so this can be asserted at all.
    const hash = '0x' + 'b'.repeat(64)
    expect(explorerTxUrl(null, hash, 'tron')).toContain('tronscan.org')
    expect(explorerTxUrl(null, hash, 'tron_nile')).toContain('nile.tronscan.org')
    expect(explorerTxUrl(null, hash, 'base')).toContain('basescan.org')
    expect(explorerTxUrl(null, hash, 'base_sepolia')).toContain(
      'sepolia.basescan.org',
    )

    for (const key of BACKEND_KEYS) {
      const url = explorerTxUrl(null, hash, key) ?? ''
      if (key !== 'base' && key !== 'base_sepolia') {
        expect(url).not.toContain('basescan.org')
      }
    }
    // An unidentifiable chain gets no link rather than a plausible wrong one.
    expect(explorerTxUrl(null, hash, 'chain:999999')).toBeNull()
  })
})
