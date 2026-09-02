/**
 * Hydration determinism for the /app dashboard.
 *
 * Two independent ways the dashboard used to render differently on the server
 * than in the browser, each of which makes React discard the server HTML and
 * re-render the whole root (the 418 → 423 pair):
 *
 *   1. AMBIENT FORMATTING — the payments table (below).
 *   2. AMBIENT CLOCK — the home page's TIME column read `Date.now()` in the
 *      render body, so the server pass and the hydration pass timestamped the
 *      same row at different instants.
 *
 * ── 1. Ambient formatting ────────────────────────────────────────────────
 *
 * The date and amount cells were formatted through module-scope
 * `Intl.DateTimeFormat(undefined, …)` / `Intl.NumberFormat(undefined, …)`
 * (payments/page.tsx). `undefined` means "resolve from the ambient
 * environment" — Node's ICU default in the server process, the visitor's
 * browser locale + timezone on the client. Two different answers for one row.
 * Observed in the running app against the same intent:
 *
 *   UTC / en-US      → "Jul 8, 2026, 11:30 PM"
 *   Asia/Tokyo/ja-JP → "2026/07/09 8:30"        ← a different calendar day
 *
 * These tests pin the contract that the table's output is a pure function of
 * its props, independent of the ambient environment.
 *
 * HOW AMBIENT RESOLUTION IS VARIED. `process.env.TZ` is NOT usable here: inside
 * Jest's jsdom environment, assigning it does not change what
 * `new Intl.DateTimeFormat(undefined)` resolves to (verified — it stays the
 * machine zone), because the formatters are built in the test VM context. So
 * ambient resolution is modelled directly: `withAmbient()` swaps in an
 * `Intl.DateTimeFormat`/`NumberFormat` that supplies a default locale and
 * timeZone ONLY when the caller left them unspecified. That is precisely what a
 * real runtime does, and it means a call site passing explicit values is
 * unaffected — which is the fix, and the reason these tests go from red to
 * green.
 *
 * WHY THE ISOLATED IMPORT: the formatters are constructed at MODULE SCOPE, so
 * they freeze the ambient environment at import time. Each pass therefore
 * re-imports the page inside `jest.isolateModules()` with the ambient shim
 * already installed.
 *
 * SCOPE NOTE: today `useOrgPayments` fetches in an effect, so the real SSR pass
 * emits an empty <tbody> and this mismatch is not reachable in production. The
 * hook is mocked here so a row exists on the FIRST render — this asserts the
 * rendering contract that becomes load-bearing the moment a row is ever
 * server-rendered (RSC, prefetch, initialData). The `/2026/` fixture guards
 * exist so a refactor that stops rendering the date fails this suite rather
 * than turning it into a silent no-op.
 */
const ROW = {
  intent_id: 'pi_deadbeef00000001',
  amount: 1234.5,
  currency: 'USDC',
  chain: 'base_sepolia',
  status: 'pending',
  recipient: '0x1111111111111111111111111111111111111111',
  split: null,
  tx_hash: null,
  matched_tx_hash: null,
  // 23:30Z — any zone east of UTC puts this on the following calendar day.
  created_at: '2026-07-08T23:30:00.000Z',
  expires_at: null,
}

jest.mock('next-intl', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@/test-utils/intlMock').intlModuleMock(),
)

jest.mock('@/i18n/navigation', () => ({
  // require INSIDE the factory so React resolves in the CURRENT registry
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  Link: (props: any) => require('react').createElement('a', props),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({ data: { access_token: 'tok' }, status: 'authenticated' }),
}))

jest.mock('@/hooks/useCurrentOrg', () => ({
  useCurrentOrg: () => ({
    activeOrg: { id: 'o1', name: 'Org' },
    role: 'admin',
    loading: false,
    isAuthed: true,
  }),
}))

// The create modal pulls in the wagmi/viem stack; irrelevant to formatting.
jest.mock('@/components/app/CreatePaymentModal', () => ({
  CreatePaymentModal: () => null,
}))

// A recent transaction, so the home page's TIME column actually renders on the
// FIRST pass (the real hook fetches in an effect and would render an empty
// tbody). `SERVER_CLOCK` puts it ~1h in the past.
const SERVER_CLOCK = Date.UTC(2026, 6, 9, 12, 0, 0)
const TX_ISO = new Date(SERVER_CLOCK - 3_600_000).toISOString()

jest.mock('@/hooks/useOrgStats', () => ({
  useOrgStats: () => ({
    stats: {
      volume_24h: 1234,
      volume_24h_delta_pct: 1,
      transactions_24h: 1,
      transactions_24h_delta: 0,
      total_balance: 0,
      total_balance_chains: 0,
      active_clients: 0,
      active_clients_this_week: 0,
      recent_transactions: [
        {
          id: 1,
          tx_hash: '0xabc',
          type: 'payment',
          amount_usd: 10,
          amount_usd_known: true,
          currency: 'USDC',
          chain_key: 'base',
          status: 'confirmed',
          recipient: '0x1111111111111111111111111111111111111111',
          timestamp_iso: TX_ISO,
        },
      ],
      volume_24h_unpriced_count: 0,
      volume_24h_unpriced_symbols: [],
      settlement_wallet_set: true,
      has_api_key: true,
      has_paid_payment: true,
    },
    loading: false,
    error: false,
    isAuthed: true,
    reload: async () => {},
  }),
}))

jest.mock('@/hooks/useOrgPayments', () => ({
  useOrgPayments: () => ({
    records: [ROW],
    total: 1,
    page: 1,
    perPage: 20,
    hasPrev: false,
    hasNext: false,
    loading: false,
    error: null,
    isAuthed: true,
    statusFilter: '',
    setStatusFilter: () => {},
    setPage: () => {},
    reload: async () => {},
    createIntent: async () => {},
    cancelIntent: async () => {},
  }),
}))

type Ambient = { locale: string; timeZone: string }

const SERVER: Ambient = { locale: 'en-US', timeZone: 'UTC' }
const CLIENT: Ambient = { locale: 'ja-JP', timeZone: 'Asia/Tokyo' }

/**
 * Run `fn` with the ambient locale/timezone that unspecified `Intl` options
 * resolve to. Explicit arguments from the caller always win — exactly as in a
 * real runtime — so a pinned call site is immune to this shim.
 */
function withAmbient<T>(ambient: Ambient, fn: (mod: any) => T): T {
  const RealDateTimeFormat = Intl.DateTimeFormat
  const RealNumberFormat = Intl.NumberFormat

  const fakeDTF = function (locale?: any, options?: any) {
    return new RealDateTimeFormat(locale ?? ambient.locale, {
      ...options,
      timeZone: options?.timeZone ?? ambient.timeZone,
    })
  } as unknown as typeof Intl.DateTimeFormat

  const fakeNF = function (locale?: any, options?: any) {
    return new RealNumberFormat(locale ?? ambient.locale, options)
  } as unknown as typeof Intl.NumberFormat

  ;(Intl as any).DateTimeFormat = fakeDTF
  ;(Intl as any).NumberFormat = fakeNF
  try {
    let out!: T
    jest.isolateModules(() => {
      out = fn({
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        React: require('react'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        server: require('react-dom/server'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        client: require('react-dom/client'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        Page: require('@/app/[locale]/app/payments/page').default,
      })
    })
    return out
  } finally {
    ;(Intl as any).DateTimeFormat = RealDateTimeFormat
    ;(Intl as any).NumberFormat = RealNumberFormat
  }
}

afterEach(() => {
  jest.resetModules()
})

// Guard the guard: on a small-ICU runtime the two ambients could collapse and
// every assertion below would pass for the wrong reason.
beforeAll(() => {
  const t = Date.UTC(2026, 6, 8, 23, 30)
  const fmt = (a: Ambient) =>
    new Intl.DateTimeFormat(a.locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: a.timeZone,
    }).format(t)
  expect(fmt(SERVER)).not.toBe(fmt(CLIENT))
})

it('renders the payments table identically under any ambient locale/timezone', () => {
  const onServer = withAmbient(SERVER, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )
  const onClient = withAmbient(CLIENT, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )

  // Fixture guards: the date and amount cells are actually rendered.
  expect(onServer).toMatch(/2026/)
  expect(onServer).toMatch(/USDC/)

  expect(onClient).toBe(onServer)
})

it('hydrates server markup in a differently-configured browser with no recoverable error', () => {
  const html = withAmbient(SERVER, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )

  const container = document.createElement('div')
  container.innerHTML = html
  document.body.appendChild(container)
  expect(container.textContent).toMatch(/2026/) // fixture guard

  const errors = withAmbient(CLIENT, ({ React, client, Page }) => {
    const seen: Error[] = []
    ;(globalThis as unknown as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT =
      true
    let root: { unmount: () => void }
    // React 18.3 exposes `act` on the React package itself; the
    // react-dom/test-utils version logs a deprecation error of its own.
    React.act(() => {
      root = client.hydrateRoot(container, React.createElement(Page), {
        onRecoverableError: (e: Error) => seen.push(e),
      })
    })
    React.act(() => root.unmount())
    return seen
  })

  container.remove()
  expect(errors.map((e) => e.message)).toEqual([])
})

// ── 2. Ambient clock — the /app home TIME column ─────────────────────────
//
// `Date.now()` in a render body means the server pass and the hydration pass
// timestamp the same row at different instants. A row rendered "1 hour ago" on
// the server becomes "3 days ago" in a browser that loads it later (or, far
// more commonly in production, "29 seconds ago" vs "30 seconds ago" — the same
// mismatch, one tick apart). `useClientNow()` returns null for both of those
// passes and the row falls back to an absolute UTC stamp, so they agree by
// construction; the relative label is a post-mount upgrade.

const CLIENT_CLOCK = SERVER_CLOCK + 3 * 86_400_000

/** Load the home page in a fresh registry with `Date.now` pinned to `clock`. */
function atClock<T>(clock: number, fn: (mod: any) => T): T {
  const spy = jest.spyOn(Date, 'now').mockReturnValue(clock)
  try {
    let out!: T
    jest.isolateModules(() => {
      out = fn({
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        React: require('react'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        server: require('react-dom/server'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        client: require('react-dom/client'),
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        Page: require('@/app/[locale]/app/page').default,
      })
    })
    return out
  } finally {
    spy.mockRestore()
  }
}

it('renders the home activity table identically whatever the render-time clock', () => {
  const early = atClock(SERVER_CLOCK, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )
  const late = atClock(CLIENT_CLOCK, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )

  // Fixture guards: the TIME cell really is rendered on this pass, as an
  // absolute stamp (never blank — the pre-mount fallback must still show the
  // user a time) and NOT as the clock-dependent relative label.
  expect(early).toMatch(/UTC/)
  expect(early).not.toMatch(/ago/)

  expect(late).toBe(early)
})

it('hydrates home markup three days later with no recoverable error', () => {
  const html = atClock(SERVER_CLOCK, ({ React, server, Page }) =>
    server.renderToString(React.createElement(Page)),
  )

  const container = document.createElement('div')
  container.innerHTML = html
  document.body.appendChild(container)
  expect(container.textContent).toMatch(/UTC/) // fixture guard

  const errors = atClock(CLIENT_CLOCK, ({ React, client, Page }) => {
    const seen: Error[] = []
    ;(globalThis as unknown as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT =
      true
    let root: { unmount: () => void }
    React.act(() => {
      root = client.hydrateRoot(container, React.createElement(Page), {
        onRecoverableError: (e: Error) => seen.push(e),
      })
    })
    React.act(() => root.unmount())
    return seen
  })

  container.remove()
  expect(errors.map((e) => e.message)).toEqual([])
})
