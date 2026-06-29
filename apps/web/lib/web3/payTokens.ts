/**
 * lib/web3/payTokens.ts — Base Sepolia pay-token registry for the /pay checkout.
 *
 * SINGLE SOURCE OF TRUTH for which tokens the params-driven /pay route offers.
 * Addresses, decimals and the `enabled` flag mirror the deployed RSendsRouter's
 * on-chain feeConfig (verified read-only against Base Sepolia). A token is
 * offered only when `enabled === true`; the checkout additionally confirms
 * enablement live via `quoteFee` so a token can never reach pay() and revert
 * UnsupportedToken.
 *
 * This cut ships USDC only (the one enabled stablecoin on the deployed router).
 * EURC is carried as `comingSoon` (enabled:false) until its on-chain feeConfig
 * is flipped by the owner; native ETH is intentionally not offered here.
 */
import { getAddress, type Address } from 'viem'

/** Base Sepolia. */
export const CHAIN_ID = 84532

/** Deployed RSendsRouter (immutable). */
export const RSENDS_ROUTER: Address = getAddress('0x2Ec353815F2Cd382628d0D399F8d80959C1758CA')

/** Fee recipient configured on-chain (owner == feeCollector). */
export const FEE_COLLECTOR: Address = getAddress('0x0e056Ce14D1D56f799588f4760E5C39d47f14B82')

/** Native-ETH gas faucet hint surfaced in the testnet badge. */
export const ETH_FAUCET_URL = 'https://docs.base.org/tools/network-faucets'

export interface PayToken {
  symbol: string
  name: string
  /** ERC-20 contract address on Base Sepolia. */
  address: Address
  decimals: number
  /** Mirrors on-chain feeConfig[token].enabled — true only when payable today. */
  enabled: boolean
  /** Shown disabled ("coming soon") in the generator until enabled on-chain. */
  comingSoon?: boolean
  /** Smallest human amount we accept (UI validation, not on-chain). */
  minAmount: string
  /** Where a prospect tops up testnet balance. */
  faucetUrl: string
}

export const PAY_TOKENS: PayToken[] = [
  {
    symbol: 'USDC',
    name: 'USD Coin (Base Sepolia)',
    address: getAddress('0x036CbD53842c5426634e7929541eC2318f3dCF7e'),
    decimals: 6,
    enabled: true,
    minAmount: '0.01',
    faucetUrl: 'https://faucet.circle.com',
  },
  {
    symbol: 'EURC',
    name: 'Euro Coin (Base Sepolia)',
    address: getAddress('0x808456652fdb597867f38412077A9182bf77359F'),
    decimals: 6,
    enabled: false,
    comingSoon: true,
    minAmount: '0.01',
    faucetUrl: 'https://faucet.circle.com',
  },
]

/** Lookup by symbol (case-insensitive) or by 0x address (checksum-insensitive). */
export function getPayToken(symbolOrAddress: string): PayToken | undefined {
  const q = symbolOrAddress.trim()
  if (!q) return undefined
  const bySymbol = PAY_TOKENS.find((t) => t.symbol.toLowerCase() === q.toLowerCase())
  if (bySymbol) return bySymbol
  if (/^0x[0-9a-fA-F]{40}$/.test(q)) {
    const lc = q.toLowerCase()
    return PAY_TOKENS.find((t) => t.address.toLowerCase() === lc)
  }
  return undefined
}

/** Tokens payable right now (used by the generator's select + checkout gate). */
export function getEnabledPayTokens(): PayToken[] {
  return PAY_TOKENS.filter((t) => t.enabled)
}
