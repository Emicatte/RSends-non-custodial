import {
  humanizeTxError,
  isTransientNetworkError,
  isUnsupportedChainError,
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

// ── The wallet itself refuses the chain ──────────────────────────
//
// Observed on production with Coinbase Smart Wallet, which answers
// "Base Sepolia is not supported. Try another blockchain." in its own window.
// This is a limitation OF THE WALLET: nothing was sent, nothing was charged,
// and no amount of retrying the same wallet can change it. It must never be
// classified as a failed payment, and never as a network outage either — the
// chain is fine, the wallet just will not go there.

describe('isUnsupportedChainError', () => {
  it('recognizes the viem switch-chain family', () => {
    for (const message of [
      'ChainNotConfiguredError: Chain "84532" not configured for connector "coinbaseWalletSDK".',
      'SwitchChainError: An error occurred when attempting to switch chain.',
      'Unrecognized chain ID "0x14a34". Try adding the chain using wallet_addEthereumChain first.',
      'Unsupported chain id: 84532',
      'Unsupported network',
      'This wallet does not support the requested network',
    ]) {
      expect({ message, unsupported: isUnsupportedChainError(new Error(message)) }).toEqual({
        message,
        unsupported: true,
      })
    }
  })

  it('recognizes the EIP-1193 4902 code and the wallet-facing wording', () => {
    expect(isUnsupportedChainError({ code: 4902, message: 'Unrecognized chain ID' })).toBe(true)
    expect(
      isUnsupportedChainError(
        new Error('Base Sepolia is not supported. Try another blockchain.'),
      ),
    ).toBe(true)
  })

  it('sees through viem wrapping a 4902 as a USER REJECTION', () => {
    // Measured shape (viem@2.47.4, injected connector refusing Base Sepolia).
    // The headline says the payer rejected it; the payer did no such thing,
    // and the truth is in Details. Classifying this as a rejection would tell
    // them they cancelled a prompt their wallet never showed them.
    const wrapped = new Error(
      'User rejected the request.\n\nDetails: Unrecognized chain ID "0x14a34". ' +
        'Base Sepolia is not supported. Try another blockchain.\nVersion: viem@2.47.4',
    )
    expect(isUnsupportedChainError(wrapped)).toBe(true)
    // ...and the nested provider code is honoured even under a 4001 wrapper.
    const nested = Object.assign(new Error('User rejected the request.'), {
      code: 4001,
      cause: { code: 4902, message: 'Unrecognized chain ID' },
    })
    expect(isUnsupportedChainError(nested)).toBe(true)
  })

  it('does NOT swallow the UnsupportedToken contract error', () => {
    // Same prefix, entirely different meaning: that one IS an answer from the
    // chain about the token, and it must keep reaching the `failed` branch.
    expect(isUnsupportedChainError(new Error('UnsupportedToken()'))).toBe(false)
    expect(
      isUnsupportedChainError(
        new Error('reverted with custom error UnsupportedToken(address)'),
      ),
    ).toBe(false)
    expect(
      isUnsupportedChainError(new Error('execution reverted: UnsupportedToken()')),
    ).toBe(false)
  })

  it('does NOT classify rejections or transport faults as unsupported', () => {
    for (const message of [
      'User rejected the request.',
      'User denied transaction signature.',
      'HTTP request failed. Status: 503. Details: no backend is currently healthy',
      'Failed to fetch',
      'insufficient funds for gas',
    ]) {
      expect({ message, unsupported: isUnsupportedChainError(new Error(message)) }).toEqual({
        message,
        unsupported: false,
      })
    }
  })

  it('is safe on null and non-Error values', () => {
    expect(isUnsupportedChainError(null)).toBe(false)
    expect(isUnsupportedChainError(undefined)).toBe(false)
    expect(isUnsupportedChainError('Unsupported chain id: 84532')).toBe(true)
  })
})
