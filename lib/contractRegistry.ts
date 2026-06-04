/**
 * lib/contractRegistry.ts — Multi-Chain Contract Registry
 *
 * Chain supportate:
 *   8453   — Base Mainnet    ✅
 *   1      — Ethereum Mainnet ✅
 *   84532  — Base Sepolia    ✅
 *   11155111 — Sepolia       (solo ETH)
 *
 * ⚠️  IMPORTANTE — NEXT_PUBLIC_* e Next.js:
 *   Next.js sostituisce process.env.NEXT_PUBLIC_* SOLO quando la chiave
 *   è scritta come stringa letterale nel codice sorgente.
 *   NON funziona con accesso dinamico tipo process.env[variabile].
 *   Ogni riferimento deve essere esplicito:
 *     ✅  process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA
 *     ❌  const k = 'NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA'; process.env[k]
 */

export type ChainId = number

export const POOL_FEE = {
  LOWEST: 100,
  LOW:    500,
  MEDIUM: 3_000,
  HIGH:   10_000,
} as const

export interface TokenConfig {
  address:       `0x${string}`
  decimals:      number
  symbol:        string
  name:          string
  logoURI:       string
  gasless:       boolean
  isEurc:        boolean
  isNative:      boolean
  poolFeeToWETH: number
}

export interface NetworkRegistry {
  chainId:       number
  chainName:     string
  isL2:          boolean
  feeRouter:     `0x${string}`
  // FeeRouter ABI generation (M1 slice B). 'v4' (default) = single-signer
  // oracle (bytes); 'v6' = threshold multisig (bytes[]). A chain opts into the
  // multisig by setting version: 'v6' once a V5/V6 router is deployed there.
  version?:      'v4' | 'v6'
  permit2:       `0x${string}`
  weth:          `0x${string}`
  swapRouter:    `0x${string}`
  rpcUrl:        string
  blockExplorer: string
  tokens:        Record<string, TokenConfig>
  gasWarning?:   string
}

// ── Indirizzi globali (deterministici su tutte le chain EVM) ───────────────
const PERMIT2     = '0x000000000022D473030F116dDEE9F6B43aC78BA3' as `0x${string}`
const SWAP_ROUTER = '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45' as `0x${string}`

// ── Logo CDN (TrustWallet) ─────────────────────────────────────────────────
const LOGOS = {
  ETH:   'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/info/logo.png',
  USDC:  'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/assets/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48/logo.png',
  USDT:  'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/assets/0xdAC17F958D2ee523a2206206994597C13D831ec7/logo.png',
  EURC:  'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/assets/0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c/logo.png',
  cbBTC: 'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/bitcoin/info/logo.png',
  WBTC:  'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/assets/0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599/logo.png',
  DEGEN: 'https://assets.coingecko.com/coins/images/34515/small/android-chrome-512x512.png',
}

// ── Token Base (stessi indirizzi su Mainnet e Sepolia) ─────────────────────
const BASE_TOKENS: Record<string, TokenConfig> = {
  ETH: {
    address:  '0x0000000000000000000000000000000000000000',
    decimals: 18, symbol: 'ETH', name: 'Ethereum',
    logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
    poolFeeToWETH: 0,
  },
  USDC: {
    address:  '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    decimals: 6, symbol: 'USDC', name: 'USD Coin',
    logoURI: LOGOS.USDC, gasless: true, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  USDT: {
    address:  '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2',
    decimals: 6, symbol: 'USDT', name: 'Tether USD',
    logoURI: LOGOS.USDT, gasless: true, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  EURC: {
    address:  '0x60a3E35Cc3064fC371f477011b3E9dd2313ec445',
    decimals: 6, symbol: 'EURC', name: 'Euro Coin',
    logoURI: LOGOS.EURC, gasless: true, isEurc: true, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  cbBTC: {
    address:  '0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf',
    decimals: 8, symbol: 'cbBTC', name: 'Coinbase Wrapped BTC',
    logoURI: LOGOS.cbBTC, gasless: false, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.MEDIUM,
  },
  DEGEN: {
    address:  '0x4eDBc9320305298056041910220E3663A92540B6',
    decimals: 18, symbol: 'DEGEN', name: 'Degen',
    logoURI: LOGOS.DEGEN, gasless: false, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.MEDIUM,
  },
}

// ── Token Ethereum Mainnet ─────────────────────────────────────────────────
const ETH_MAINNET_TOKENS: Record<string, TokenConfig> = {
  ETH: {
    address:  '0x0000000000000000000000000000000000000000',
    decimals: 18, symbol: 'ETH', name: 'Ethereum',
    logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
    poolFeeToWETH: 0,
  },
  USDC: {
    address:  '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
    decimals: 6, symbol: 'USDC', name: 'USD Coin',
    logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  USDT: {
    address:  '0xdAC17F958D2ee523a2206206994597C13D831ec7',
    decimals: 6, symbol: 'USDT', name: 'Tether USD',
    logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  EURC: {
    address:  '0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c',
    decimals: 6, symbol: 'EURC', name: 'Euro Coin',
    logoURI: LOGOS.EURC, gasless: false, isEurc: true, isNative: false,
    poolFeeToWETH: POOL_FEE.LOW,
  },
  WBTC: {
    address:  '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
    decimals: 8, symbol: 'WBTC', name: 'Wrapped Bitcoin',
    logoURI: LOGOS.WBTC, gasless: false, isEurc: false, isNative: false,
    poolFeeToWETH: POOL_FEE.MEDIUM,
  },
}

// ══════════════════════════════════════════════════════════════════════════
//  FIX CRITICO — Accesso LETTERALE a process.env.NEXT_PUBLIC_*
//
//  Next.js sostituisce process.env.NEXT_PUBLIC_XYZ con il valore reale
//  SOLO se la stringa completa "process.env.NEXT_PUBLIC_XYZ" appare nel
//  codice sorgente. L'accesso dinamico process.env[key] NON viene
//  sostituito → restituisce sempre undefined lato client.
//
//  Prima (BROKEN):
//    const env = (key: string) => process.env[key]   // ❌ sempre undefined
//    env('NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA')
//
//  Dopo (FIXED):
//    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA   // ✅ inlined
// ══════════════════════════════════════════════════════════════════════════

function baseFeeRouter(): `0x${string}` {
  return (
    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ADDRESS ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_V3_ADDRESS ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_ADDRESS ??
    '0x0000000000000000000000000000000000000000'
  ) as `0x${string}`
}

function sepoliaFeeRouter(): `0x${string}` {
  return (
    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ADDRESS ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_V3_ADDRESS ??
    process.env.NEXT_PUBLIC_FEE_ROUTER_ADDRESS ??
    '0x0000000000000000000000000000000000000000'
  ) as `0x${string}`
}

function ethFeeRouter(): `0x${string}` {
  return (
    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ETH ??
    '0x0000000000000000000000000000000000000000'
  ) as `0x${string}`
}

// ── Nuove chain — literal access per Next.js inlining ─────────────────────
function optimismFeeRouter(): `0x${string}` {
  return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_OPTIMISM ?? '0x0000000000000000000000000000000000000000') as `0x${string}`
}
function arbitrumFeeRouter(): `0x${string}` {
  return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ARBITRUM ?? '0x0000000000000000000000000000000000000000') as `0x${string}`
}
function polygonFeeRouter(): `0x${string}` {
  return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_POLYGON ?? '0x0000000000000000000000000000000000000000') as `0x${string}`
}
function bnbFeeRouter(): `0x${string}` {
  return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BNB ?? '0x0000000000000000000000000000000000000000') as `0x${string}`
}
function avalancheFeeRouter(): `0x${string}` {
  return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_AVALANCHE ?? '0x0000000000000000000000000000000000000000') as `0x${string}`
}

// ══════════════════════════════════════════════════════════════════════════
const REGISTRY: { [chainId: number]: NetworkRegistry } = {

  // ── Base Mainnet ─────────────────────────────────────────────────────────
  8453: {
    chainId:       8453,
    chainName:     'Base',
    isL2:          true,
    feeRouter:     baseFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0x4200000000000000000000000000000000000006',
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://mainnet.base.org',
    blockExplorer: 'https://basescan.org',
    tokens:        BASE_TOKENS,
  },

  // ── Base Sepolia ──────────────────────────────────────────────────────────
  84532: {
    chainId:       84532,
    chainName:     'Base Sepolia',
    isL2:          true,
    feeRouter:     sepoliaFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0x4200000000000000000000000000000000000006',
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://sepolia.base.org',
    blockExplorer: 'https://sepolia.basescan.org',
    tokens:        BASE_TOKENS,
  },

  // ── Ethereum Mainnet ──────────────────────────────────────────────────────
  1: {
    chainId:       1,
    chainName:     'Ethereum',
    isL2:          false,
    feeRouter:     ethFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://eth-mainnet.g.alchemy.com/v2/demo',
    blockExplorer: 'https://etherscan.io',
    gasWarning:    'Gas su Ethereum L1 è più costoso. Considera Base per transazioni minori.',
    tokens:        ETH_MAINNET_TOKENS,
  },

  // ── Arbitrum ──────────────────────────────────────────────────────────────
  42161: {
    chainId:       42161,
    chainName:     'Arbitrum One',
    isL2:          true,
    feeRouter:     arbitrumFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1' as `0x${string}`,
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://arb1.arbitrum.io/rpc',
    blockExplorer: 'https://arbiscan.io',
    tokens: {
      ETH: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'ETH', name: 'Ether',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
      USDT: {
        address: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9' as `0x${string}`,
        decimals: 6, symbol: 'USDT', name: 'Tether USD',
        logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Optimism ──────────────────────────────────────────────────────────────
  10: {
    chainId:       10,
    chainName:     'Optimism',
    isL2:          true,
    feeRouter:     optimismFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0x4200000000000000000000000000000000000006' as `0x${string}`,
    swapRouter:    '0xE592427A0AEce92De3Edee1F18E0157C05861564' as `0x${string}`,
    rpcUrl:        'https://mainnet.optimism.io',
    blockExplorer: 'https://optimistic.etherscan.io',
    tokens: {
      ETH: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'ETH', name: 'Ether',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
      USDT: {
        address: '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58' as `0x${string}`,
        decimals: 6, symbol: 'USDT', name: 'Tether USD',
        logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── BNB Chain ─────────────────────────────────────────────────────────────
  56: {
    chainId:       56,
    chainName:     'BNB Chain',
    isL2:          false,
    feeRouter:     bnbFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c' as `0x${string}`,
    swapRouter:    '0xB971eF87ede563556b2ED4b1C0b0019111Dd85d2' as `0x${string}`,
    rpcUrl:        'https://bsc-dataseed.binance.org',
    blockExplorer: 'https://bscscan.com',
    tokens: {
      BNB: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'BNB', name: 'BNB',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d' as `0x${string}`,
        decimals: 18, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
      USDT: {
        address: '0x55d398326f99059fF775485246999027B3197955' as `0x${string}`,
        decimals: 18, symbol: 'USDT', name: 'Tether USD',
        logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Polygon ───────────────────────────────────────────────────────────────
  137: {
    chainId:       137,
    chainName:     'Polygon',
    isL2:          true,
    feeRouter:     polygonFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270' as `0x${string}`,
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://polygon-rpc.com',
    blockExplorer: 'https://polygonscan.com',
    tokens: {
      POL: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'POL', name: 'POL',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
      USDT: {
        address: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F' as `0x${string}`,
        decimals: 6, symbol: 'USDT', name: 'Tether USD',
        logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Avalanche ─────────────────────────────────────────────────────────────
  43114: {
    chainId:       43114,
    chainName:     'Avalanche',
    isL2:          false,
    feeRouter:     avalancheFeeRouter(),
    permit2:       PERMIT2,
    weth:          '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7' as `0x${string}`,
    swapRouter:    '0xbB00FF08d01d300023C629e8ffFfCB65a5A578cE' as `0x${string}`,
    rpcUrl:        'https://api.avax.network/ext/bc/C/rpc',
    blockExplorer: 'https://snowtrace.io',
    tokens: {
      AVAX: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'AVAX', name: 'Avalanche',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
      USDT: {
        address: '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7' as `0x${string}`,
        decimals: 6, symbol: 'USDT', name: 'Tether USD',
        logoURI: LOGOS.USDT, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── ZKsync Era ────────────────────────────────────────────────────────────
  324: {
    chainId:       324,
    chainName:     'ZKsync Era',
    isL2:          true,
    feeRouter:     '0x0000000000000000000000000000000000000000' as `0x${string}`,
    permit2:       PERMIT2,
    weth:          '0x5AEa5775959fBC2557Cc8789bC1bf90A239D9a91' as `0x${string}`,
    swapRouter:    '0x99c56385dB8B93f67A212e6473437b93117E77C3' as `0x${string}`,
    rpcUrl:        'https://mainnet.era.zksync.io',
    blockExplorer: 'https://explorer.zksync.io',
    tokens: {
      ETH: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'ETH', name: 'Ether',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0x1d17CBcF0D6D143135aE902365D2E5e2A16538D4' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Celo ──────────────────────────────────────────────────────────────────
  42220: {
    chainId:       42220,
    chainName:     'Celo',
    isL2:          false,
    feeRouter:     '0x0000000000000000000000000000000000000000' as `0x${string}`,
    permit2:       PERMIT2,
    weth:          '0x471EcE3750Da237f93B8E339c536989b8978a438' as `0x${string}`,
    swapRouter:    '0x5615CDAb10dc425a742d643d949a7F474C01abc4' as `0x${string}`,
    rpcUrl:        'https://forno.celo.org',
    blockExplorer: 'https://celoscan.io',
    tokens: {
      CELO: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'CELO', name: 'Celo',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDC: {
        address: '0xcebA9300f2b948710d2653dD7B07f33A8B32118C' as `0x${string}`,
        decimals: 6, symbol: 'USDC', name: 'USD Coin',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Blast ─────────────────────────────────────────────────────────────────
  81457: {
    chainId:       81457,
    chainName:     'Blast',
    isL2:          true,
    feeRouter:     '0x0000000000000000000000000000000000000000' as `0x${string}`,
    permit2:       PERMIT2,
    weth:          '0x4300000000000000000000000000000000000004' as `0x${string}`,
    swapRouter:    '0x549FEB8c9bd4c12Ad2AB27022dA12492aC452B66' as `0x${string}`,
    rpcUrl:        'https://rpc.blast.io',
    blockExplorer: 'https://blastscan.io',
    tokens: {
      ETH: {
        address: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        decimals: 18, symbol: 'ETH', name: 'Ether',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
      USDB: {
        address: '0x4300000000000000000000000000000000000003' as `0x${string}`,
        decimals: 18, symbol: 'USDB', name: 'USDB',
        logoURI: LOGOS.USDC, gasless: false, isEurc: false, isNative: false,
        poolFeeToWETH: POOL_FEE.LOW,
      },
    },
  },

  // ── Ethereum Sepolia ──────────────────────────────────────────────────────
  11155111: {
    chainId:       11155111,
    chainName:     'Sepolia',
    isL2:          false,
    feeRouter:     '0x0000000000000000000000000000000000000000',
    permit2:       PERMIT2,
    weth:          '0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14',
    swapRouter:    SWAP_ROUTER,
    rpcUrl:        'https://rpc.sepolia.org',
    blockExplorer: 'https://sepolia.etherscan.io',
    tokens: {
      ETH: {
        address:  '0x0000000000000000000000000000000000000000',
        decimals: 18, symbol: 'ETH', name: 'Ethereum (Sepolia)',
        logoURI: LOGOS.ETH, gasless: false, isEurc: false, isNative: true,
        poolFeeToWETH: 0,
      },
    },
  },
}

// ── Tron Registry (separato perché non è EVM) ────────────────────────────
export const TRON_REGISTRY = {
  mainnet: {
    chainId: 'tron-mainnet' as const,
    chainName: 'TRON',
    feeRouter: 'T_INDIRIZZO_DAL_DEPLOY', // ← metti indirizzo reale dopo deploy
    swapRouter: 'TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax', // SunSwap V2
    wtrx: 'TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR',
    blockExplorer: 'https://tronscan.org',
    tokens: {
      TRX:  { address: null, decimals: 6, symbol: 'TRX',  name: 'TRON',       isNative: true  },
      USDT: { address: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', decimals: 6,  symbol: 'USDT', name: 'Tether USD', isNative: false },
      USDC: { address: 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8', decimals: 6,  symbol: 'USDC', name: 'USD Coin',   isNative: false },
      USDD: { address: 'TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn', decimals: 18, symbol: 'USDD', name: 'USDD',       isNative: false },
    },
  },
  shasta: {
    chainId: 'tron-shasta' as const,
    chainName: 'TRON Shasta',
    feeRouter: '', // testnet address dopo deploy
    swapRouter: '',
    wtrx: '',
    blockExplorer: 'https://shasta.tronscan.org',
    tokens: {
      TRX: { address: null, decimals: 6, symbol: 'TRX', name: 'TRON (Shasta)', isNative: true },
    },
  },
} as const

export function getTronRegistry(network: 'mainnet' | 'shasta' = 'mainnet') {
  return TRON_REGISTRY[network]
}

export function isTronFeeRouterAvailable(network: 'mainnet' | 'shasta' = 'mainnet'): boolean {
  return !!TRON_REGISTRY[network].feeRouter
}

// ── FeeRouter deployment map ──────────────────────────────────────────────
/**
 * Chain su cui FeeRouterV4 è deployato e verificato.
 * Quando deployerai su altre chain, aggiungi qui l'indirizzo.
 */
const FEE_ROUTER_DEPLOYMENTS: Partial<Record<number, `0x${string}`>> = {
  8453:  baseFeeRouter(),        // Base Mainnet
  84532: sepoliaFeeRouter(),     // Base Sepolia
  1:     ethFeeRouter(),         // Ethereum Mainnet
  10:    optimismFeeRouter(),    // Optimism
  42161: arbitrumFeeRouter(),    // Arbitrum
  137:   polygonFeeRouter(),     // Polygon
  56:    bnbFeeRouter(),         // BNB Chain
  43114: avalancheFeeRouter(),   // Avalanche
}

export function getFeeRouterAddress(chainId: number): `0x${string}` | null {
  const addr = FEE_ROUTER_DEPLOYMENTS[chainId]
  if (!addr || addr === '0x0000000000000000000000000000000000000000') return null
  return addr
}

export function isFeeRouterAvailable(chainId: number): boolean {
  return getFeeRouterAddress(chainId) !== null
}

// ── API pubblica ───────────────────────────────────────────────────────────

export function getRegistry(chainId: number): NetworkRegistry | null {
  return REGISTRY[chainId] ?? null
}

export function getToken(chainId: number, symbol: string): TokenConfig | null {
  return REGISTRY[chainId]?.tokens[symbol] ?? null
}

export function getSupportedChains(): number[] {
  return Object.keys(REGISTRY).map(Number)
}

export function isChainSupported(chainId: number): boolean {
  return chainId in REGISTRY
}

export function findChainForToken(symbol: string): number[] {
  return Object.entries(REGISTRY)
    .filter(([, reg]) => symbol in reg.tokens)
    .map(([id]) => Number(id))
}

// EUR exchange rates mock (produzione: Chainlink)
export const EUR_RATES: { [symbol: string]: number } = {
  ETH:   2200,
  USDC:  0.92,
  USDT:  0.92,
  EURC:  1.0,
  cbBTC: 88000,
  WBTC:  88000,
  DEGEN: 0.003,
  BNB:   600,
  POL:   0.45,
  AVAX:  35,
  CELO:  0.75,
  OP:    2.5,
  USDB:  1.0,
  ARB:   1.1,
  BTCB:  88000,
  cUSD:  0.92,
  TRX:   0.12,
  USDD:  0.92,
}