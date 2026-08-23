import {
  humanizeTxError,
  isTransientNetworkError,
  isUserRejection,
} from '@/lib/web3/humanizeTxError'

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

// ── Transient vs terminal ────────────────────────────────────────
//
// A network fault invites a retry; a revert does not. Getting this wrong in
// the transient direction makes the page nag about a dead transaction; in the
// terminal direction it tells a payer their money is gone when it is not.

describe('isTransientNetworkError', () => {
  it('classifies the outage of record as transient', () => {
    expect(
      isTransientNetworkError(
        new Error(
          'HTTP request failed. Status: 503. Details: no backend is currently healthy to serve traffic',
        ),
      ),
    ).toBe(true)
    expect(isTransientNetworkError(new Error('-32011 no backend is currently healthy'))).toBe(true)
  })

  it('classifies ordinary transport faults as transient', () => {
    for (const message of [
      'Failed to fetch',
      'fetch failed',
      'network error',
      'The request timed out.',
      'HTTP request failed. Status: 502',
      'connect ECONNREFUSED 127.0.0.1:8545',
      'Load failed',
    ]) {
      expect({ message, transient: isTransientNetworkError(new Error(message)) }).toEqual({
        message,
        transient: true,
      })
    }
  })

  it('does NOT classify contract or wallet outcomes as transient', () => {
    for (const message of [
      'execution reverted: FeeTooHigh()',
      'execution reverted',
      'UnsupportedToken()',
      'User rejected the request.',
      'insufficient funds for gas * price + value',
      'transfer amount exceeds balance',
    ]) {
      expect({ message, transient: isTransientNetworkError(new Error(message)) }).toEqual({
        message,
        transient: false,
      })
    }
  })

  it('is safe on null and non-Error values', () => {
    expect(isTransientNetworkError(null)).toBe(false)
    expect(isTransientNetworkError(undefined)).toBe(false)
    expect(isTransientNetworkError('Failed to fetch')).toBe(true)
  })
})
