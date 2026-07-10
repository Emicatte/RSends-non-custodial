/**
 * lib/web3/explorer — explorer URLs for the hosted checkout, sourced from the
 * central per-chain registry (contractRegistry.blockExplorer). Success,
 * failure, and the trust footer's View contract link all flow through here.
 */
import { explorerAddressUrl, explorerTxUrl } from '@/lib/web3/explorer'

const HASH = '0x' + 'ab'.repeat(32)
const ROUTER = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'

describe('explorer links', () => {
  it('builds tx links from the central chain config', () => {
    expect(explorerTxUrl(84532, HASH)).toBe(
      `https://sepolia.basescan.org/tx/${HASH}`,
    )
    expect(explorerTxUrl(8453, HASH)).toBe(`https://basescan.org/tx/${HASH}`)
  })

  it('builds address links (View contract)', () => {
    expect(explorerAddressUrl(84532, ROUTER)).toBe(
      `https://sepolia.basescan.org/address/${ROUTER}`,
    )
  })

  it('falls back to the Base explorer for unknown/missing chain ids', () => {
    expect(explorerTxUrl(999999, HASH)).toBe(`https://basescan.org/tx/${HASH}`)
    expect(explorerTxUrl(null, HASH)).toBe(`https://basescan.org/tx/${HASH}`)
  })
})
