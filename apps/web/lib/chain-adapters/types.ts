/**
 * lib/chain-adapters/types.ts — Universal blockchain interface
 *
 * Defines the adapter pattern for cross-chain support (EVM, Solana, Tron).
 * Each chain family implements ChainAdapter; the UI codes against this
 * interface without knowing which chain is active.
 */

export type ChainFamily = 'evm' | 'solana' | 'tron'

export interface UniversalAddress {
  /** Address in the chain's native format */
  raw: string
  /** Truncated address for display */
  display: string
  /** Chain family */
  family: ChainFamily
}

export interface UniversalToken {
  /** Contract address (EVM), mint address (Solana), or contract (Tron) */
  address: string
  symbol: string
  name: string
  decimals: number
  chainId: number | string  // number for EVM, string for Solana ('mainnet-beta')
  chainFamily: ChainFamily
  logoURI?: string
  isNative?: boolean
}

export interface UniversalBalance {
  token: UniversalToken
  balance: string          // String to handle BigInt cross-chain
  formattedBalance: string
  usdValue: number | null
}

export interface UniversalTxRequest {
  type: 'transfer' | 'swap' | 'approve'
  from: string
  to: string
  token: UniversalToken
  amount: string           // In smallest unit (wei, lamports, sun)
  data?: string            // Calldata for EVM, instruction data for Solana
}

export interface UniversalTxResult {
  hash: string
  chainId: number | string
  chainFamily: ChainFamily
  status: 'pending' | 'confirmed' | 'failed'
  explorerUrl: string
}

export interface ChainAdapter {
  /** Chain family identifier */
  family: ChainFamily

  /** Chain ID (number for EVM, string for Solana/Tron) */
  chainId: number | string

  /** Human-readable name */
  name: string

  /** Validate an address for this chain */
  isValidAddress(address: string): boolean

  /** Format address for display (truncated) */
  formatAddress(address: string): string

  /** Get native token balance */
  getNativeBalance(address: string): Promise<UniversalBalance>

  /** Get specific token balance */
  getTokenBalance(address: string, token: UniversalToken): Promise<UniversalBalance>

  /** Get all token balances for an address */
  getAllBalances(address: string): Promise<UniversalBalance[]>

  /** Explorer URL for a transaction hash */
  getTxExplorerUrl(hash: string): string

  /** Explorer URL for an address */
  getAddressExplorerUrl(address: string): string
}

/**
 * Extended adapter for chains with integrated DEX swap support.
 */
export interface SwapCapableAdapter extends ChainAdapter {
  /** Get a swap quote */
  getSwapQuote(params: {
    tokenIn: UniversalToken
    tokenOut: UniversalToken
    amountIn: string
    slippageBps: number
  }): Promise<{
    amountOut: string
    priceImpact: number
    route: string[]
    estimatedGas: string
  }>

  /** Build a swap transaction to be signed */
  buildSwapTx(params: {
    tokenIn: UniversalToken
    tokenOut: UniversalToken
    amountIn: string
    amountOutMin: string
    recipient: string
    deadline: number
  }): Promise<UniversalTxRequest>
}

/**
 * Extended adapter for chains with FeeRouter deployment (EVM-only for now).
 */
export interface FeeRouterCapableAdapter extends SwapCapableAdapter {
  /** Build a fee-routed transfer transaction */
  buildFeeRouterTx(params: {
    recipient: string
    token: UniversalToken
    amount: string
    oracleSignature: string
    deadline: number
    nonce: string
  }): Promise<UniversalTxRequest>
}
