/**
 * app/tokens/tokenRegistry.ts — Unified Multi-Chain Token Registry
 *
 * SINGLE SOURCE OF TRUTH per tutti i token supportati da RSends.
 * Il backend (rpagos-backend/app/tokens/registry.py) rispecchia questi dati.
 *
 * Chains supportate:
 *   1      — Ethereum Mainnet
 *   10     — Optimism
 *   56     — BNB Chain
 *   137    — Polygon
 *   324    — ZKsync Era
 *   8453   — Base Mainnet
 *   42161  — Arbitrum One
 *   42220  — Celo
 *   43114  — Avalanche
 *   81457  — Blast
 *   84532  — Base Sepolia (testnet)
 */

export interface TokenInfo {
  symbol: string
  name: string
  decimals: number
  address: string | null       // null = nativo (ETH)
  chainId: number
  isNative: boolean
  logoUrl: string              // icona locale /tokens/*.svg
  coingeckoId: string          // per price feed
  minAmount: string            // importo minimo in unità human (es. "0.001")
  batchDistributorAddress?: string  // contratto RSends per batch distribution
}

export const SUPPORTED_CHAINS = {
  1:     { name: 'Ethereum',      nativeCurrency: 'ETH',  explorerUrl: 'https://etherscan.io',           iconUrl: '/chains/ethereum.svg' },
  10:    { name: 'Optimism',      nativeCurrency: 'ETH',  explorerUrl: 'https://optimistic.etherscan.io', iconUrl: '/chains/optimism.svg' },
  56:    { name: 'BNB Chain',     nativeCurrency: 'BNB',  explorerUrl: 'https://bscscan.com',             iconUrl: '/chains/bnb.svg' },
  137:   { name: 'Polygon',       nativeCurrency: 'POL',  explorerUrl: 'https://polygonscan.com',         iconUrl: '/chains/polygon.svg' },
  324:   { name: 'ZKsync Era',    nativeCurrency: 'ETH',  explorerUrl: 'https://explorer.zksync.io',      iconUrl: '/chains/zksync.svg' },
  8453:  { name: 'Base',          nativeCurrency: 'ETH',  explorerUrl: 'https://basescan.org',            iconUrl: '/chains/base.svg' },
  42161: { name: 'Arbitrum One',  nativeCurrency: 'ETH',  explorerUrl: 'https://arbiscan.io',             iconUrl: '/chains/arbitrum.svg' },
  42220: { name: 'Celo',          nativeCurrency: 'CELO', explorerUrl: 'https://celoscan.io',             iconUrl: '/chains/celo.svg' },
  43114: { name: 'Avalanche',     nativeCurrency: 'AVAX', explorerUrl: 'https://snowtrace.io',            iconUrl: '/chains/avalanche.svg' },
  81457: { name: 'Blast',         nativeCurrency: 'ETH',  explorerUrl: 'https://blastscan.io',            iconUrl: '/chains/blast.svg' },
  84532: { name: 'Base Sepolia',  nativeCurrency: 'ETH',  explorerUrl: 'https://sepolia.basescan.org',    iconUrl: '/chains/base.svg' },
  728126428: { name: 'TRON',      nativeCurrency: 'TRX',  explorerUrl: 'https://tronscan.org',            iconUrl: '/chains/tron.svg' },
} as const

export type ChainId = keyof typeof SUPPORTED_CHAINS

export const TOKEN_LIST: TokenInfo[] = [
  // ═══════════ BASE MAINNET (8453) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 8453, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
    batchDistributorAddress: '0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', chainId: 8453, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
    batchDistributorAddress: '0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2', chainId: 8453, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'DAI', name: 'Dai Stablecoin', decimals: 18,
    address: '0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb', chainId: 8453, isNative: false,
    logoUrl: '/tokens/dai.svg', coingeckoId: 'dai',
    minAmount: '0.01',
  },
  {
    symbol: 'WETH', name: 'Wrapped Ether', decimals: 18,
    address: '0x4200000000000000000000000000000000000006', chainId: 8453, isNative: false,
    logoUrl: '/tokens/weth.svg', coingeckoId: 'weth',
    minAmount: '0.0001',
  },
  {
    symbol: 'cbBTC', name: 'Coinbase BTC', decimals: 8,
    address: '0xcbB7C0000AB88B473b1f5aFd9ef808440eed33Bf', chainId: 8453, isNative: false,
    logoUrl: '/tokens/btc.svg', coingeckoId: 'bitcoin',
    minAmount: '0.00001',
  },

  // ═══════════ BASE SEPOLIA (84532) ═══════════
  {
    symbol: 'ETH', name: 'Ether (Sepolia)', decimals: 18,
    address: null, chainId: 84532, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
    batchDistributorAddress: '0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3',
  },
  {
    symbol: 'USDC', name: 'USDC (Sepolia)', decimals: 6,
    address: '0x036CbD53842c5426634e7929541eC2318f3dCF7e', chainId: 84532, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },

  // ═══════════ ETHEREUM MAINNET (1) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 1, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.001',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', chainId: 1, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0xdAC17F958D2ee523a2206206994597C13D831ec7', chainId: 1, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },

  // ═══════════ ARBITRUM ONE (42161) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 42161, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', chainId: 42161, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9', chainId: 42161, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'ARB', name: 'Arbitrum', decimals: 18,
    address: '0x912CE59144191C1204E64559FE8253a0e49E6548', chainId: 42161, isNative: false,
    logoUrl: '/tokens/arb.svg', coingeckoId: 'arbitrum',
    minAmount: '0.1',
  },

  // ═══════════ OPTIMISM (10) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 10, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85', chainId: 10, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58', chainId: 10, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'OP', name: 'Optimism', decimals: 18,
    address: '0x4200000000000000000000000000000000000042', chainId: 10, isNative: false,
    logoUrl: '/tokens/op.svg', coingeckoId: 'optimism',
    minAmount: '0.1',
  },

  // ═══════════ BNB CHAIN (56) ═══════════
  {
    symbol: 'BNB', name: 'BNB', decimals: 18,
    address: null, chainId: 56, isNative: true,
    logoUrl: '/tokens/bnb.svg', coingeckoId: 'binancecoin',
    minAmount: '0.001',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 18,
    address: '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', chainId: 56, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 18,
    address: '0x55d398326f99059fF775485246999027B3197955', chainId: 56, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'BTCB', name: 'Bitcoin BEP2', decimals: 18,
    address: '0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c', chainId: 56, isNative: false,
    logoUrl: '/tokens/btc.svg', coingeckoId: 'bitcoin',
    minAmount: '0.00001',
  },

  // ═══════════ POLYGON (137) ═══════════
  {
    symbol: 'POL', name: 'POL', decimals: 18,
    address: null, chainId: 137, isNative: true,
    logoUrl: '/tokens/pol.svg', coingeckoId: 'polygon-ecosystem-token',
    minAmount: '0.1',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359', chainId: 137, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F', chainId: 137, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'WBTC', name: 'Wrapped BTC', decimals: 8,
    address: '0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6', chainId: 137, isNative: false,
    logoUrl: '/tokens/btc.svg', coingeckoId: 'bitcoin',
    minAmount: '0.00001',
  },

  // ═══════════ AVALANCHE (43114) ═══════════
  {
    symbol: 'AVAX', name: 'Avalanche', decimals: 18,
    address: null, chainId: 43114, isNative: true,
    logoUrl: '/tokens/avax.svg', coingeckoId: 'avalanche-2',
    minAmount: '0.01',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E', chainId: 43114, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7', chainId: 43114, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },

  // ═══════════ ZKSYNC ERA (324) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 324, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0x1d17CBcF0D6D143135aE902365D2E5e2A16538D4', chainId: 324, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },

  // ═══════════ CELO (42220) ═══════════
  {
    symbol: 'CELO', name: 'Celo', decimals: 18,
    address: null, chainId: 42220, isNative: true,
    logoUrl: '/tokens/celo.svg', coingeckoId: 'celo',
    minAmount: '0.1',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: '0xcebA9300f2b948710d2653dD7B07f33A8B32118C', chainId: 42220, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'cUSD', name: 'Celo Dollar', decimals: 18,
    address: '0x765DE816845861e75A25fCA122bb6898B8B1282a', chainId: 42220, isNative: false,
    logoUrl: '/tokens/cusd.svg', coingeckoId: 'celo-dollar',
    minAmount: '0.01',
  },

  // ═══════════ BLAST (81457) ═══════════
  {
    symbol: 'ETH', name: 'Ether', decimals: 18,
    address: null, chainId: 81457, isNative: true,
    logoUrl: '/tokens/eth.svg', coingeckoId: 'ethereum',
    minAmount: '0.0001',
  },
  {
    symbol: 'USDB', name: 'USDB', decimals: 18,
    address: '0x4300000000000000000000000000000000000003', chainId: 81457, isNative: false,
    logoUrl: '/tokens/usdb.svg', coingeckoId: 'usdb',
    minAmount: '0.01',
  },
  // ═══════════ TRON MAINNET (728126428) ═══════════
  {
    symbol: 'TRX', name: 'TRON', decimals: 6,
    address: null, chainId: 728126428, isNative: true,
    logoUrl: '/tokens/trx.svg', coingeckoId: 'tron',
    minAmount: '1',
  },
  {
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    address: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', chainId: 728126428, isNative: false,
    logoUrl: '/tokens/usdt.svg', coingeckoId: 'tether',
    minAmount: '0.01',
  },
  {
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    address: 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8', chainId: 728126428, isNative: false,
    logoUrl: '/tokens/usdc.svg', coingeckoId: 'usd-coin',
    minAmount: '0.01',
  },
  {
    symbol: 'USDD', name: 'USDD', decimals: 18,
    address: 'TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn', chainId: 728126428, isNative: false,
    logoUrl: '/tokens/usdd.svg', coingeckoId: 'usdd',
    minAmount: '0.01',
  },
]

// ═══════════ HELPER FUNCTIONS ═══════════

/** Get all tokens for a specific chain */
export function getTokensForChain(chainId: number): TokenInfo[] {
  return TOKEN_LIST.filter(t => t.chainId === chainId)
}

/** Get a specific token by symbol and chain */
export function getToken(symbol: string, chainId: number): TokenInfo | undefined {
  return TOKEN_LIST.find(t => t.symbol === symbol && t.chainId === chainId)
}

/** Get native token for a chain */
export function getNativeToken(chainId: number): TokenInfo | undefined {
  return TOKEN_LIST.find(t => t.chainId === chainId && t.isNative)
}

/** Get token by contract address and chain */
export function getTokenByAddress(address: string, chainId: number): TokenInfo | undefined {
  return TOKEN_LIST.find(
    t => t.chainId === chainId && t.address?.toLowerCase() === address.toLowerCase()
  )
}

/** All unique symbols across all chains */
export function getAllSymbols(): string[] {
  return [...new Set(TOKEN_LIST.map(t => t.symbol))]
}

/** All unique coingecko IDs (for batch price fetch) */
export function getAllCoingeckoIds(): string[] {
  return [...new Set(TOKEN_LIST.map(t => t.coingeckoId))]
}
