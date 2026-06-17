/**
 * src/config/chains.ts — EVM Chain Registry
 *
 * Central registry of all supported EVM chains with RPC endpoints,
 * block explorers, native currency info, and Uniswap V3 contract addresses.
 */

import type { EVMChain, SupportedChainId, ChainRegistry } from '../types/chain';

/** All supported EVM chains */
export const CHAINS: ChainRegistry = {
  // ── Ethereum Mainnet ────────────────────────────────────────
  1: {
    id: 1,
    name: 'Ethereum',
    shortName: 'ETH',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_ETHEREUM || 'https://eth.llamarpc.com',
      fallback: ['https://rpc.ankr.com/eth', 'https://ethereum.publicnode.com'],
    },
    blockExplorers: [{ name: 'Etherscan', url: 'https://etherscan.io' }],
    iconUrl: '/chains/ethereum.svg',
    testnet: false,
  },
  // ── Optimism ────────────────────────────────────────────────
  10: {
    id: 10,
    name: 'Optimism',
    shortName: 'OP',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_OPTIMISM || 'https://mainnet.optimism.io',
      fallback: ['https://optimism.publicnode.com', 'https://rpc.ankr.com/optimism'],
    },
    blockExplorers: [{ name: 'Optimistic Etherscan', url: 'https://optimistic.etherscan.io' }],
    iconUrl: '/chains/optimism.svg',
    testnet: false,
  },
  // ── BNB Chain ───────────────────────────────────────────────
  56: {
    id: 56,
    name: 'BNB Chain',
    shortName: 'BNB',
    nativeCurrency: { name: 'BNB', symbol: 'BNB', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_BNB || 'https://bsc-dataseed.binance.org',
      fallback: ['https://bsc.publicnode.com', 'https://rpc.ankr.com/bsc'],
    },
    blockExplorers: [{ name: 'BscScan', url: 'https://bscscan.com' }],
    iconUrl: '/chains/bnb.svg',
    testnet: false,
  },
  // ── Polygon ─────────────────────────────────────────────────
  137: {
    id: 137,
    name: 'Polygon',
    shortName: 'MATIC',
    nativeCurrency: { name: 'POL', symbol: 'POL', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_POLYGON || 'https://polygon-rpc.com',
      fallback: ['https://polygon-bor.publicnode.com', 'https://rpc.ankr.com/polygon'],
    },
    blockExplorers: [{ name: 'PolygonScan', url: 'https://polygonscan.com' }],
    iconUrl: '/chains/polygon.svg',
    testnet: false,
  },
  // ── ZKsync Era ──────────────────────────────────────────────
  324: {
    id: 324,
    name: 'ZKsync Era',
    shortName: 'ZK',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_ZKSYNC || 'https://mainnet.era.zksync.io',
      fallback: ['https://zksync-era.blockpi.network/v1/rpc/public'],
    },
    blockExplorers: [{ name: 'ZKsync Explorer', url: 'https://explorer.zksync.io' }],
    iconUrl: '/chains/zksync.svg',
    testnet: false,
  },
  // ── Base ────────────────────────────────────────────────────
  8453: {
    id: 8453,
    name: 'Base',
    shortName: 'BASE',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_BASE || 'https://mainnet.base.org',
      fallback: ['https://base.llamarpc.com', 'https://base.publicnode.com'],
    },
    blockExplorers: [{ name: 'BaseScan', url: 'https://basescan.org' }],
    iconUrl: '/chains/base.svg',
    testnet: false,
  },
  // ── Arbitrum One ────────────────────────────────────────────
  42161: {
    id: 42161,
    name: 'Arbitrum One',
    shortName: 'ARB',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_ARBITRUM || 'https://arb1.arbitrum.io/rpc',
      fallback: ['https://arbitrum.llamarpc.com', 'https://arbitrum-one.publicnode.com'],
    },
    blockExplorers: [{ name: 'Arbiscan', url: 'https://arbiscan.io' }],
    iconUrl: '/chains/arbitrum.svg',
    testnet: false,
  },
  // ── Celo ────────────────────────────────────────────────────
  42220: {
    id: 42220,
    name: 'Celo',
    shortName: 'CELO',
    nativeCurrency: { name: 'Celo', symbol: 'CELO', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_CELO || 'https://forno.celo.org',
      fallback: ['https://celo.publicnode.com', 'https://rpc.ankr.com/celo'],
    },
    blockExplorers: [{ name: 'CeloScan', url: 'https://celoscan.io' }],
    iconUrl: '/chains/celo.svg',
    testnet: false,
  },
  // ── Avalanche ───────────────────────────────────────────────
  43114: {
    id: 43114,
    name: 'Avalanche',
    shortName: 'AVAX',
    nativeCurrency: { name: 'Avalanche', symbol: 'AVAX', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_AVALANCHE || 'https://api.avax.network/ext/bc/C/rpc',
      fallback: ['https://avalanche.publicnode.com', 'https://rpc.ankr.com/avalanche'],
    },
    blockExplorers: [{ name: 'Snowtrace', url: 'https://snowtrace.io' }],
    iconUrl: '/chains/avalanche.svg',
    testnet: false,
  },
  // ── Blast ───────────────────────────────────────────────────
  81457: {
    id: 81457,
    name: 'Blast',
    shortName: 'BLAST',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_BLAST || 'https://rpc.blast.io',
      fallback: ['https://blast.blockpi.network/v1/rpc/public'],
    },
    blockExplorers: [{ name: 'BlastScan', url: 'https://blastscan.io' }],
    iconUrl: '/chains/blast.svg',
    testnet: false,
  },
  // ── Base Sepolia (testnet) ──────────────────────────────────
  84532: {
    id: 84532,
    name: 'Base Sepolia',
    shortName: 'BASE-SEP',
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: {
      default: process.env.NEXT_PUBLIC_RPC_BASE_SEPOLIA || 'https://sepolia.base.org',
      fallback: ['https://base-sepolia.publicnode.com'],
    },
    blockExplorers: [{ name: 'BaseScan Sepolia', url: 'https://sepolia.basescan.org' }],
    iconUrl: '/chains/base.svg',
    testnet: true,
  },
};

/** Ordered list of chain IDs (mainnets first, testnets last) */
export const CHAIN_IDS: SupportedChainId[] = [
  1, 8453, 42161, 10, 137, 56, 43114, 42220, 81457, 324, 84532,
];

/** Mainnet-only chain IDs (excludes testnets) */
export const MAINNET_CHAIN_IDS: SupportedChainId[] = CHAIN_IDS.filter(
  (id) => !CHAINS[id].testnet,
);

/** Default chain to connect to */
export const DEFAULT_CHAIN_ID: SupportedChainId = 8453;

/** Map<number, EVMChain> for O(1) lookup */
export const CHAIN_MAP: ReadonlyMap<number, EVMChain> = new Map(
  CHAIN_IDS.map((id) => [id, CHAINS[id]]),
);

/**
 * Get chain config by ID.
 * @returns The EVMChain config, or undefined if unsupported.
 */
export function getChain(chainId: number): EVMChain | undefined {
  return CHAINS[chainId as SupportedChainId];
}

/**
 * Get chain config by ID (Map-based O(1) lookup).
 * @returns The EVMChain config, or undefined if unsupported.
 */
export function getChainById(chainId: number): EVMChain | undefined {
  return CHAIN_MAP.get(chainId);
}

/**
 * Get all supported chains as an array.
 * @returns Array of EVMChain objects, ordered by CHAIN_IDS.
 */
export function getSupportedChains(): EVMChain[] {
  return CHAIN_IDS.map((id) => CHAINS[id]);
}

/**
 * Get the primary RPC URL for a chain.
 * @returns The default RPC URL, or undefined if chain is unsupported.
 */
export function getChainRpcUrl(chainId: number): string | undefined {
  return getChainById(chainId)?.rpcUrls.default;
}

/**
 * Check if a chain ID is supported.
 */
export function isSupportedChain(chainId: number): chainId is SupportedChainId {
  return chainId in CHAINS;
}
