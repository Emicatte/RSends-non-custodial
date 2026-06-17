/**
 * CCIP chain selectors and contract addresses.
 * Separato da contractRegistry.ts per non toccare nulla.
 */

export interface CCIPChainConfig {
  chainId: number
  chainName: string
  ccipRouter: `0x${string}`
  chainSelector: bigint
  linkToken: `0x${string}`
  senderContract: `0x${string}`    // RSendCCIPSender address
  receiverContract: `0x${string}`  // RSendCCIPReceiver address
}

const ZERO = '0x0000000000000000000000000000000000000000' as `0x${string}`

// Aggiorna con indirizzi reali dopo il deploy
export const CCIP_CHAINS: Record<number, CCIPChainConfig> = {
  8453: {
    chainId: 8453, chainName: 'Base',
    ccipRouter: '0x881e3A65B4d4a04dD529061dd0071cf975F58bCD',
    chainSelector: 15971525489660198786n,
    linkToken: '0x88Fb150BDc53A65fe94Dea0c9BA0a6dAf8C6e196',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  1: {
    chainId: 1, chainName: 'Ethereum',
    ccipRouter: '0x80226fc0Ee2b096224EeAc085Bb9a8cba1146f7D',
    chainSelector: 5009297550715157269n,
    linkToken: '0x514910771AF9Ca656af840dff83E8264EcF986CA',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  42161: {
    chainId: 42161, chainName: 'Arbitrum',
    ccipRouter: '0x141fa059441E0ca23ce184B6A78bafD2A517DdE8',
    chainSelector: 4949039107694359620n,
    linkToken: '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  10: {
    chainId: 10, chainName: 'Optimism',
    ccipRouter: '0x3206695CaE29952f4b0c22a169725a865bc8Ce0f',
    chainSelector: 3734403246176062136n,
    linkToken: '0x350a791Bfc2C21F9Ed5d10980Dad2e2638ffa7f6',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  137: {
    chainId: 137, chainName: 'Polygon',
    ccipRouter: '0x849c5ED5a80F5B408Dd4969b78c2C8fdf0565Bfe',
    chainSelector: 4051577828743386545n,
    linkToken: '0xb0897686c545045aFc77CF20eC7A532E3120E0F1',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  56: {
    chainId: 56, chainName: 'BNB',
    ccipRouter: '0x34B03Cb9086d7D758AC55af71584F81A598759FE',
    chainSelector: 11344663589394136015n,
    linkToken: '0x404460C6A5EdE2D891e8297795264fDe62ADBB75',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
  43114: {
    chainId: 43114, chainName: 'Avalanche',
    ccipRouter: '0xF4c7E640EdA248ef95972845a62bdC74237805dB',
    chainSelector: 6433500567565415381n,
    linkToken: '0x5947BB275c521040051D82396192181b413227A3',
    senderContract: ZERO,
    receiverContract: ZERO,
  },
}

export function getCCIPConfig(chainId: number): CCIPChainConfig | null {
  return CCIP_CHAINS[chainId] ?? null
}

export function isCCIPAvailable(sourceChainId: number, destChainId: number): boolean {
  const src = CCIP_CHAINS[sourceChainId]
  const dst = CCIP_CHAINS[destChainId]
  if (!src || !dst) return false
  return src.senderContract !== ZERO && dst.receiverContract !== ZERO
}

export function getCCIPChainSelector(chainId: number): bigint | null {
  return CCIP_CHAINS[chainId]?.chainSelector ?? null
}

// Token supportati da CCIP per cross-chain (subset di tutti i token)
// CCIP supporta solo token specifici per lane — verifica su docs.chain.link
export const CCIP_SUPPORTED_TOKENS: Record<number, string[]> = {
  8453:  ['USDC', 'LINK', 'WETH'],
  1:     ['USDC', 'USDT', 'LINK', 'WETH', 'WBTC'],
  42161: ['USDC', 'LINK', 'WETH', 'WBTC'],
  10:    ['USDC', 'LINK', 'WETH'],
  137:   ['USDC', 'LINK'],
  56:    ['USDC', 'LINK'],
  43114: ['USDC', 'LINK'],
}
