import { humanizeTxError } from '@/lib/web3/humanizeTxError'

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
