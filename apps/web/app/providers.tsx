'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { WagmiProvider, createConfig, http } from 'wagmi'
import { base } from 'wagmi/chains'
import dynamic from 'next/dynamic'
import {
  useState, useEffect, useCallback,
  createContext, useContext,
} from 'react'
import { usePathname } from 'next/navigation'
import { registerAdapter } from '../lib/chain-adapters/registry'
import { createEVMAdapter } from '../lib/chain-adapters/evm-adapter'
import { createSolanaAdapter } from '../lib/chain-adapters/solana-adapter'
import { createTronAdapter } from '../lib/chain-adapters/tron-adapter'

const SolanaProviders = dynamic(() => import('./providers-solana'), { ssr: false })
const TronProvider = dynamic(() => import('./providers-tron').then(m => ({ default: m.TronProvider })), { ssr: false })
// Lazy: contains all wallet SDK imports (MetaMask SDK, Coinbase WalletLink, etc.)
// Loaded only when walletRequested becomes true — avoids window.ethereum probing
// on the landing page before user clicks Connect.
const WalletStackFull = dynamic(() => import('./providers-wallet-stack'), { ssr: false })

// ── Register all chain adapters at module load ────────────────────────────
const EVM_CHAIN_IDS = [1, 10, 56, 137, 324, 8453, 42161, 42220, 43114, 81457, 84532]
EVM_CHAIN_IDS.forEach(id => registerAdapter(createEVMAdapter(id)))
registerAdapter(createSolanaAdapter())
registerAdapter(createTronAdapter())

// ── Valori letterali — necessari per Wagmi v2 type safety ──────────────────
const CHAIN = {
  BASE:         8453   as const,
  MAINNET:      1      as const,
  BASE_SEPOLIA: 84532  as const,
  SEPOLIA:      11155111 as const,
} as const

type SupportedChainId = typeof CHAIN[keyof typeof CHAIN]

// ── Safe config for landing pre-click ─────────────────────────────────────
// Zero connectors → no MetaMask/Coinbase SDK loaded → no window.ethereum probe.
// Wagmi hooks (useAccount, useChainId, useBalance, useReadContract, useSignMessage)
// remain callable and return disconnected state.
const safeConfig = createConfig({
  chains:     [base],
  connectors: [],
  transports: { [base.id]: http('https://mainnet.base.org') },
  ssr:        false,
})

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 8_000, retry: 2 } },
  })
}

// ── Wallet mount gate ─────────────────────────────────────────────────────
interface WalletMount {
  walletRequested: boolean
  mountWallet:     () => void
}

const WalletMountContext = createContext<WalletMount>({
  walletRequested: false,
  mountWallet:     () => {},
})

export const useWalletMount = () => useContext(WalletMountContext)

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient)
  const [mounted, setMounted] = useState(false)
  const [explicitlyRequested, setExplicitlyRequested] = useState(false)
  const pathname = usePathname()
  useEffect(() => setMounted(true), [])
  const mountWallet = useCallback(() => setExplicitlyRequested(true), [])

  // Admin / pay / merchant: bypass providers entirely (no wallet needed)
  if (pathname?.startsWith('/admin') || pathname?.startsWith('/pay') || pathname?.startsWith('/merchant')) {
    return <>{children}</>
  }

  // /app merchant dashboard: same bypass. Non-custodial — the merchant operates
  // with a session, never a wallet connection; nothing in the /app tree touches
  // wagmi, Solana or Tron. Wallet linking (SIWE) lives under /settings/wallets,
  // which keeps the full stack below.
  if (pathname?.match(/^\/[a-z]{2}\/app(\/|$)/)) {
    return <>{children}</>
  }

  // Marketing pages: same bypass. Nothing in their tree touches wagmi or
  // react-query (session auth lives above in AuthSessionProvider), and the
  // mounted gate below would otherwise blank their server-rendered HTML —
  // these pages must SSR fully (SEO + they work with JS disabled).
  if (pathname?.match(/^\/[a-z]{2}\/(pricing|how-it-works|vision|team)(\/|$)/)) {
    return <>{children}</>
  }

  // Landing pages: '/' or any /<two-letter-locale>. We do NOT load wallet
  // SDKs here — only after user clicks Connect (sets explicitlyRequested).
  // Inside /app and other deep routes we mount the full wallet stack from
  // the first render so reconnect works on refresh.
  const isLanding = pathname === '/' || pathname?.match(/^\/[a-z]{2}$/) !== null
  const walletRequested = !isLanding || explicitlyRequested

  const innerChrome = mounted ? (
    <SolanaProviders>
      <TronProvider>
        {children}
      </TronProvider>
    </SolanaProviders>
  ) : null

  return (
    <WalletMountContext.Provider value={{ walletRequested, mountWallet }}>
      {walletRequested ? (
        <WalletStackFull
          autoOpenModal={isLanding && explicitlyRequested}
          reconnectOnMount={!isLanding}
          queryClient={queryClient}
        >
          {innerChrome}
        </WalletStackFull>
      ) : (
        <WagmiProvider config={safeConfig} reconnectOnMount={false}>
          <QueryClientProvider client={queryClient}>
            {innerChrome}
          </QueryClientProvider>
        </WagmiProvider>
      )}
    </WalletMountContext.Provider>
  )
}

// ── Export chain constants per uso nel resto dell'app ──────────────────────
export { CHAIN, type SupportedChainId }

export function decodeWalletError(error: unknown): {
  message: string; type: string; isUserAction: boolean
} {
  const raw  = error instanceof Error ? error.message : String(error)
  const code = (error as { code?: number })?.code
  if (code === 4001 || raw.includes('rejected') || raw.includes('denied'))
    return { message: 'Firma annullata senza costi.', type: 'rejected', isUserAction: true }
  if (raw.includes('OracleSignatureInvalid'))
    return { message: 'Transazione negata per policy di conformità AML.', type: 'oracle', isUserAction: false }
  if (raw.includes('MEVGuard'))
    return { message: 'Slippage non configurato.', type: 'mev', isUserAction: false }
  if (raw.includes('InsufficientLiquidity'))
    return { message: "Liquidità insufficiente. Riduci l'importo o cambia token.", type: 'liquidity', isUserAction: false }
  if (raw.includes('SlippageExceeded'))
    return { message: 'Slippage superato. Riprova.', type: 'slippage', isUserAction: false }
  if (raw.includes('insufficient funds'))
    return { message: 'Fondi insufficienti per il gas.', type: 'funds', isUserAction: false }
  return { message: 'Errore: ' + raw.slice(0, 100), type: 'unknown', isUserAction: false }
}

