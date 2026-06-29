import { getAddress } from 'viem'
import {
  PAY_TOKENS, getPayToken, getEnabledPayTokens,
  RSENDS_ROUTER, FEE_COLLECTOR, CHAIN_ID,
} from '@/lib/web3/payTokens'

describe('payTokens registry', () => {
  it('exposes the verified Base Sepolia router + feeCollector + chain', () => {
    expect(CHAIN_ID).toBe(84532)
    expect(RSENDS_ROUTER).toBe(getAddress('0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'))
    expect(FEE_COLLECTOR).toBe(getAddress('0x0e056Ce14D1D56f799588f4760E5C39d47f14B82'))
  })

  it('USDC is enabled with 6 decimals and the verified address', () => {
    const usdc = getPayToken('USDC')
    expect(usdc).toBeDefined()
    expect(usdc!.enabled).toBe(true)
    expect(usdc!.decimals).toBe(6)
    expect(usdc!.address).toBe(getAddress('0x036CbD53842c5426634e7929541eC2318f3dCF7e'))
  })

  it('looks up case-insensitively and by address', () => {
    expect(getPayToken('usdc')?.symbol).toBe('USDC')
    expect(getPayToken('0x036cbd53842c5426634e7929541ec2318f3dcf7e')?.symbol).toBe('USDC')
  })

  it('EURC is carried but not enabled (coming soon)', () => {
    const eurc = getPayToken('EURC')
    expect(eurc).toBeDefined()
    expect(eurc!.enabled).toBe(false)
    expect(eurc!.comingSoon).toBe(true)
  })

  it('getEnabledPayTokens excludes EURC and yields USDC only', () => {
    const enabled = getEnabledPayTokens()
    expect(enabled.map((t) => t.symbol)).toEqual(['USDC'])
  })

  it('unknown symbol returns undefined', () => {
    expect(getPayToken('DOGE')).toBeUndefined()
    expect(getPayToken('')).toBeUndefined()
  })

  it('every registry address is checksummed', () => {
    for (const t of PAY_TOKENS) {
      expect(t.address).toBe(getAddress(t.address))
    }
  })
})
