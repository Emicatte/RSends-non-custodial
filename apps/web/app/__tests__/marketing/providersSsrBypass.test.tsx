/**
 * Marketing pages must actually server-render: the wallet-provider mounted
 * gate (which blanks SSR output) has to be bypassed for them, exactly like
 * /admin, /pay and /merchant already are. The typewriter headline requirement
 * (full headline in server HTML, works with JS disabled) depends on this.
 */
import { renderToString } from 'react-dom/server'

let currentPathname = '/'
jest.mock('next/navigation', () => ({
  usePathname: () => currentPathname,
}))

// wagmi (like next-intl) ships untranspiled ESM Jest can't parse, and the
// wallet stack is irrelevant here — the behavior under test is the pathname
// branch in Providers, which returns before any provider mounts.
jest.mock('wagmi', () => ({
  WagmiProvider: ({ children }: any) => children,
  createConfig: () => ({}),
  http: () => ({}),
}))
jest.mock('wagmi/chains', () => ({ base: { id: 8453 } }))
jest.mock('@tanstack/react-query', () => ({
  QueryClient: class {},
  QueryClientProvider: ({ children }: any) => children,
}))
jest.mock('next/dynamic', () => () => () => null)
jest.mock('@/lib/chain-adapters/registry', () => ({ registerAdapter: () => {} }))
jest.mock('@/lib/chain-adapters/evm-adapter', () => ({ createEVMAdapter: () => ({}) }))
jest.mock('@/lib/chain-adapters/solana-adapter', () => ({ createSolanaAdapter: () => ({}) }))
jest.mock('@/lib/chain-adapters/tron-adapter', () => ({ createTronAdapter: () => ({}) }))

import { Providers } from '@/app/providers'

const MARKER = 'ssr-marker-content'

const ssrHtml = () =>
  renderToString(
    <Providers>
      <div>{MARKER}</div>
    </Providers>,
  )

describe('Providers SSR bypass', () => {
  it.each([
    '/en/vision',
    '/it/pricing',
    '/de/how-it-works',
    '/fr/team',
    '/es/vision',
  ])('server-renders children on marketing route %s', pathname => {
    currentPathname = pathname
    expect(ssrHtml()).toContain(MARKER)
  })
})
