/**
 * lib/web3/chainFamily — which flow an intent belongs to.
 *
 * The invariant under test is that the decision comes from `chain` and from
 * nothing else. `onchain === null` carries two opposite meanings — a normal
 * watch-only intent, and a broken router-chain one — and the pair of cases at
 * the bottom of this file is what keeps them apart.
 */
import { chainFamily, payFlowFor } from '@/lib/web3/chainFamily'
import { normalizeIntent, type RawPaymentIntent } from '@/lib/web3/paymentIntent'

const EXPIRES = '2030-01-01T00:00:00Z'

function intent(raw: Partial<RawPaymentIntent>) {
  return normalizeIntent(
    { status: 'pending', expires_at: EXPIRES, ...raw } as RawPaymentIntent,
    'pi_' + '0'.repeat(32),
  )
}

describe('chainFamily', () => {
  it('recognises both TRON networks', () => {
    expect(chainFamily('tron')).toBe('tron')
    expect(chainFamily('tron_nile')).toBe('tron')
  })

  it('folds case, because `chain` is stored as the merchant sent it', () => {
    // intent_service stores `chain=payload.chain` verbatim; every backend
    // reader compares with func.lower(). So does this.
    for (const chain of ['TRON', 'TrOn', 'TRON_NILE', 'Tron_Nile']) {
      expect(chainFamily(chain)).toBe('tron')
    }
  })

  it('treats every EVM chain, and every unknown one, as evm', () => {
    for (const chain of ['base', 'BASE', 'base_sepolia', 'BASE_SEPOLIA', 'ethereum']) {
      expect(chainFamily(chain)).toBe('evm')
    }
    // Unknown and absent fall to the flow that can still report a problem,
    // rather than to one that would print payment instructions for a chain we
    // know nothing about.
    expect(chainFamily('solana')).toBe('evm')
    expect(chainFamily('shasta')).toBe('evm')
    expect(chainFamily(null)).toBe('evm')
    expect(chainFamily(undefined)).toBe('evm')
    expect(chainFamily('')).toBe('evm')
  })
})

describe('payFlowFor', () => {
  it('routes a TRON intent to the instruction screen', () => {
    expect(
      payFlowFor(intent({ chain: 'TRON', currency: 'USDT', onchain: null })),
    ).toBe('tron_instructions')
  })

  it('routes an ordinary EVM intent to the wallet flow', () => {
    expect(
      payFlowFor(
        intent({
          chain: 'BASE_SEPOLIA',
          currency: 'USDC',
          onchain: {
            invoiceId: '0x' + '11'.repeat(32),
            merchant: '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA',
            token: '0x036CbD53842c5426634e7929541eC2318f3dCF7e',
            amount: '1000000',
            chainId: 84532,
            router: '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA',
            decimals: 6,
          },
        }),
      ),
    ).toBe('evm_wallet')
  })

  it('keeps an UNPAYABLE evm intent on the wallet flow', () => {
    // This is the whole point of branching on chain. `onchain` is null here
    // for the bad reason — a router-chain intent with no instructions — and it
    // must NOT be mistaken for a watch-only one, or a broken invoice would
    // render a payment address it does not have.
    const broken = intent({ chain: 'BASE', currency: 'USDC', onchain: null })
    expect(broken.onchain).toBeNull()
    expect(payFlowFor(broken)).toBe('evm_wallet')
  })

  it('keeps a TRON intent on the instruction screen even though onchain is null', () => {
    // The mirror image: same null, opposite meaning.
    const tron = intent({ chain: 'TRON', currency: 'USDT', onchain: null })
    expect(tron.onchain).toBeNull()
    expect(payFlowFor(tron)).toBe('tron_instructions')
  })
})
