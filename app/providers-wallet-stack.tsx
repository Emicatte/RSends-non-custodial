'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  WagmiProvider, createConfig, http, fallback,
  useChainId, useSwitchChain,
} from 'wagmi'
import {
  mainnet, optimism, bsc, polygon, zksync,
  base, arbitrum, celo, avalanche, blast,
  baseSepolia, sepolia,
} from 'wagmi/chains'
import {
  RainbowKitProvider, darkTheme,
  connectorsForWallets, useConnectModal,
} from '@rainbow-me/rainbowkit'
import {
  metaMaskWallet, coinbaseWallet, rainbowWallet,
  walletConnectWallet, trustWallet, ledgerWallet,
} from '@rainbow-me/rainbowkit/wallets'
import '@rainbow-me/rainbowkit/styles.css'
import { useEffect, useRef, createContext, useContext } from 'react'

const WC_PROJECT_ID = process.env.NEXT_PUBLIC_WC_PROJECT_ID!

// ── Chain literal constants (mirror of providers.tsx CHAIN) ───────────────
const CHAIN_BASE         = 8453   as const
const CHAIN_MAINNET      = 1      as const
const CHAIN_BASE_SEPOLIA = 84532  as const

// ── Multi-provider RPC with automatic failover ──────────────────────────
const ALCHEMY_KEY = process.env.NEXT_PUBLIC_ALCHEMY_API_KEY ?? ''
const INFURA_KEY  = process.env.NEXT_PUBLIC_INFURA_API_KEY ?? ''

function alchemy(sub: string) {
  return ALCHEMY_KEY
    ? http(`https://${sub}.g.alchemy.com/v2/${ALCHEMY_KEY}`, { batch: true })
    : null
}

function infura(net: string) {
  return INFURA_KEY
    ? http(`https://${net}.infura.io/v3/${INFURA_KEY}`)
    : null
}

function rpcFallback(
  alchemySub: string | null,
  infuraNet: string | null,
  ...publicUrls: string[]
) {
  const transports = [
    alchemySub ? alchemy(alchemySub) : null,
    infuraNet  ? infura(infuraNet)   : null,
    ...publicUrls.map(url => http(url)),
  ].filter(Boolean) as ReturnType<typeof http>[]

  return transports.length === 1 ? transports[0] : fallback(transports)
}

const connectors = connectorsForWallets(
  [
    {
      groupName: 'Raccomandati',
      wallets:   [metaMaskWallet, coinbaseWallet, rainbowWallet],
    },
    {
      groupName: 'Altri',
      wallets:   [walletConnectWallet, trustWallet, ledgerWallet],
    },
  ],
  { appName: 'RPagos — Omni-chain Gateway', projectId: WC_PROJECT_ID }
)

const realConfig = createConfig({
  chains: [
    base,
    mainnet,
    arbitrum,
    optimism,
    polygon,
    bsc,
    avalanche,
    zksync,
    celo,
    blast,
    baseSepolia,
    sepolia,
  ] as const,
  connectors,
  transports: {
    [base.id]:        rpcFallback('base-mainnet',    null,             'https://mainnet.base.org', 'https://base.llamarpc.com'),
    [mainnet.id]:     rpcFallback('eth-mainnet',     'mainnet',        'https://rpc.ankr.com/eth', 'https://rpc.ankr.com/eth'),
    [arbitrum.id]:    rpcFallback('arb-mainnet',     'arbitrum-mainnet', 'https://arb1.arbitrum.io/rpc'),
    [optimism.id]:    rpcFallback('opt-mainnet',     'optimism-mainnet', 'https://mainnet.optimism.io'),
    [polygon.id]:     rpcFallback('polygon-mainnet', 'polygon-mainnet', 'https://polygon-rpc.com'),
    [bsc.id]:         rpcFallback(null,              null,             'https://bsc-dataseed.binance.org', 'https://bsc-dataseed1.ninicoin.io'),
    [avalanche.id]:   rpcFallback(null,              'avalanche-mainnet', 'https://api.avax.network/ext/bc/C/rpc'),
    [zksync.id]:      rpcFallback('zksync-mainnet',  null,             'https://mainnet.era.zksync.io'),
    [celo.id]:        rpcFallback(null,              'celo-mainnet',   'https://forno.celo.org'),
    [blast.id]:       rpcFallback('blast-mainnet',   null,             'https://rpc.blast.io'),
    [baseSepolia.id]: rpcFallback('base-sepolia',    null,             'https://sepolia.base.org'),
    [sepolia.id]:     rpcFallback('eth-sepolia',     'sepolia',        'https://rpc.sepolia.org'),
  },
  ssr: false,
})

// ── Chain Guard ────────────────────────────────────────────────────────────
interface ChainGuardCtx {
  isCorrectChain:  boolean
  isL2:            boolean
  currentChainId:  number
  switchToBase:    () => void
  switchToMainnet: () => void
  gasWarning:      string | null
}

const ChainGuardContext = createContext<ChainGuardCtx>({
  isCorrectChain:  true,
  isL2:            true,
  currentChainId:  CHAIN_BASE,
  switchToBase:    () => {},
  switchToMainnet: () => {},
  gasWarning:      null,
})

function ChainGuardProvider({ children }: { children: React.ReactNode }) {
  const chainId         = useChainId()
  const { switchChain } = useSwitchChain()

  const supported: readonly number[] = [
    base.id, mainnet.id, arbitrum.id, optimism.id, polygon.id,
    bsc.id, avalanche.id, zksync.id, celo.id, blast.id,
    baseSepolia.id, sepolia.id,
  ]
  const isCorrectChain = supported.includes(chainId)
  const isL2           = chainId === CHAIN_BASE || chainId === CHAIN_BASE_SEPOLIA
  const gasWarning     = null

  return (
    <ChainGuardContext.Provider value={{
      isCorrectChain,
      isL2,
      currentChainId:  chainId,
      switchToBase:    () => switchChain({ chainId: CHAIN_BASE }),
      switchToMainnet: () => switchChain({ chainId: CHAIN_MAINNET }),
      gasWarning,
    }}>
      {children}
    </ChainGuardContext.Provider>
  )
}

export function useChainGuard() {
  return useContext(ChainGuardContext)
}

function GasWarningBanner() {
  const { gasWarning, switchToBase } = useChainGuard()
  if (!gasWarning) return null
  return (
    <div className="bf-blur-8" style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000,
      background: 'rgba(245,158,11,0.9)',
      padding: '9px 20px',
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12,
      fontFamily: 'var(--font-display)', fontSize: 13,
    }}>
      <span>⚠ {gasWarning}</span>
      <button
        onClick={switchToBase}
        style={{
          padding: '3px 12px', borderRadius: 6, border: 'none',
          background: 'rgba(0,0,0,0.2)', color: '#fff',
          fontWeight: 700, cursor: 'pointer', fontSize: 12,
        }}
      >
        Passa a Base →
      </button>
    </div>
  )
}

// ── Auto-open RainbowKit modal once after lazy mount ────────────────────
function AutoOpenConnectModal({ active }: { active: boolean }) {
  const { openConnectModal } = useConnectModal()
  const opened = useRef(false)
  useEffect(() => {
    if (active && openConnectModal && !opened.current) {
      opened.current = true
      openConnectModal()
    }
  }, [active, openConnectModal])
  return null
}

interface WalletStackProps {
  children:         React.ReactNode
  autoOpenModal:    boolean
  reconnectOnMount: boolean
  queryClient:      QueryClient
}

export default function WalletStackFull({
  children, autoOpenModal, reconnectOnMount, queryClient,
}: WalletStackProps) {
  return (
    <WagmiProvider config={realConfig} reconnectOnMount={reconnectOnMount}>
      <QueryClientProvider client={queryClient}>
        <RainbowKitProvider
          theme={darkTheme({
            accentColor:           '#00ffa3',
            accentColorForeground: '#000',
            borderRadius:          'medium',
            overlayBlur:           'small',
          })}
          modalSize="compact"
          appInfo={{ appName: 'RPagos', learnMoreUrl: 'https://rpagos.com' }}
        >
          <AutoOpenConnectModal active={autoOpenModal} />
          <ChainGuardProvider>
            <GasWarningBanner />
            {children}
          </ChainGuardProvider>
        </RainbowKitProvider>
      </QueryClientProvider>
    </WagmiProvider>
  )
}
