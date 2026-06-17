/**
 * src/types/chain.ts — EVM Chain type definitions
 *
 * Defines the shape of chain configurations used throughout the wallet connector.
 */

/** Native currency descriptor for an EVM chain */
export interface NativeCurrency {
  name: string;
  symbol: string;
  decimals: number;
}

/** Block explorer entry */
export interface BlockExplorer {
  name: string;
  url: string;
}

/** Contract addresses deployed on a specific chain */
export interface ChainContracts {
  uniswapV3Router?: `0x${string}`;
  uniswapV3Quoter?: `0x${string}`;
  uniswapV3Factory?: `0x${string}`;
  multicall3?: `0x${string}`;
  wbtc?: `0x${string}`;
}

/** Full EVM chain configuration */
export interface EVMChain {
  id: number;
  name: string;
  shortName: string;
  nativeCurrency: NativeCurrency;
  rpcUrls: { default: string; fallback: string[] };
  blockExplorers: BlockExplorer[];
  contracts?: ChainContracts;
  iconUrl?: string;
  testnet: boolean;
}

/** Supported chain IDs */
export type SupportedChainId =
  | 1       // Ethereum
  | 10      // Optimism
  | 56      // BNB Chain
  | 137     // Polygon
  | 324     // ZKsync Era
  | 8453    // Base
  | 42161   // Arbitrum One
  | 42220   // Celo
  | 43114   // Avalanche
  | 81457   // Blast
  | 84532;  // Base Sepolia (testnet)

/** Map of chain ID to chain config */
export type ChainRegistry = Record<SupportedChainId, EVMChain>;
