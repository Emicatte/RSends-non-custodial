import { humanizeTxError, isUserRejection } from '@/lib/web3/humanizeTxError'

describe('humanizeTxError', () => {
  it('maps a user rejection', () => {
    expect(humanizeTxError(new Error('User rejected the request.'))).toBe(
      'Transaction rejected in wallet.',
    )
  })

  it('maps the FeeTooHigh custom error', () => {
    expect(humanizeTxError(new Error('execution reverted: FeeTooHigh()'))).toMatch(/fee changed/i)
  })

  it('maps the UnsupportedToken custom error', () => {
    expect(humanizeTxError(new Error('reverted with custom error UnsupportedToken(address)'))).toMatch(
      /isn't accepted/i,
    )
  })

  it('maps insufficient allowance and balance distinctly', () => {
    expect(humanizeTxError(new Error('ERC20: insufficient allowance'))).toMatch(/allowance/i)
    expect(humanizeTxError(new Error('transfer amount exceeds balance'))).toMatch(/balance/i)
  })

  it('falls back to the first line of an unknown error, truncated', () => {
    const out = humanizeTxError(new Error('Something weird\nstack line'))
    expect(out).toBe('Something weird')
  })
})

describe('isUserRejection', () => {
  it('recognizes the wallet-reject family', () => {
    expect(isUserRejection(new Error('User rejected the request.'))).toBe(true)
    expect(
      isUserRejection(new Error('MetaMask Tx Signature: User denied transaction signature.')),
    ).toBe(true)
    expect(isUserRejection(new Error('User denied message signature'))).toBe(true)
  })

  it('does not classify other failures as rejection', () => {
    expect(isUserRejection(new Error('execution reverted: FeeTooHigh()'))).toBe(false)
    expect(isUserRejection(new Error('insufficient funds for gas'))).toBe(false)
    expect(isUserRejection(null)).toBe(false)
  })
})
