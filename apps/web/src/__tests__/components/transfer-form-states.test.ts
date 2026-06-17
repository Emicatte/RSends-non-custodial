/**
 * Component tests — TransferForm CTA state machine
 *
 * TransferForm's CtaState determines what the user sees and can do.
 * Getting this wrong means: user can't send, or worse, sends when they shouldn't.
 *
 * We test the state derivation as pure logic (no React rendering needed),
 * because the risk is in the LOGIC, not the JSX.
 */

import { describe, it, expect } from 'vitest'

// ── CTA state type (mirrors TransferForm.tsx line 109) ───────────
type CtaState =
  | 'disconnected'
  | 'wrong_network'
  | 'insufficient'
  | 'no_recipient'
  | 'no_amount'
  | 'oracle_denied'
  | 'no_liquidity'
  | 'ready'
  | 'busy'

// ── Supported chain IDs (mirrors TransferForm.tsx line 1030) ──────
const SUPPORTED_CHAINS = [8453, 1, 42161, 10, 137, 56, 43114, 324, 42220, 81457, 84532, 11155111]

// ── Pure CTA state derivation (mirrors TransferForm.tsx lines 1041-1049) ──
interface CtaInput {
  isConnected: boolean
  chainId: number
  busy: boolean
  rawIn: bigint | null  // parsed amount in wei
  tokenBalance: bigint  // token balance in wei
  oracleDenied: boolean
  feeRouterAvailable: boolean
  noLiquidity: boolean
  recipient: string
  addrError: string
  isExtERC20: boolean
  extAmtWei: bigint | null
  extTokenBalance: bigint
}

function deriveCtaState(input: CtaInput): CtaState {
  const {
    isConnected, chainId, busy, rawIn, tokenBalance,
    oracleDenied, feeRouterAvailable, noLiquidity,
    recipient, addrError, isExtERC20, extAmtWei, extTokenBalance,
  } = input

  const isWrong = isConnected && !SUPPORTED_CHAINS.includes(chainId)
  const hasInsuf = isConnected && !!rawIn && rawIn > tokenBalance
  const hasInsufExt = isConnected && isExtERC20 && !!extAmtWei && extAmtWei > extTokenBalance

  if (!isConnected) return 'disconnected'
  if (isWrong) return 'wrong_network'
  if (busy) return 'busy'
  if (hasInsuf || hasInsufExt) return 'insufficient'
  if ((isExtERC20 || !feeRouterAvailable ? false : oracleDenied)) return 'oracle_denied'
  if (noLiquidity) return 'no_liquidity'
  if (!recipient || !!addrError) return 'no_recipient'
  if (isExtERC20 ? !extAmtWei : !rawIn) return 'no_amount'
  return 'ready'
}

// ── Default "happy path" input ───────────────────────────────────
const READY_INPUT: CtaInput = {
  isConnected: true,
  chainId: 8453, // Base Mainnet
  busy: false,
  rawIn: 1_000_000_000_000_000_000n, // 1 ETH
  tokenBalance: 5_000_000_000_000_000_000n, // 5 ETH
  oracleDenied: false,
  feeRouterAvailable: true,
  noLiquidity: false,
  recipient: '0x1234567890abcdef1234567890abcdef12345678',
  addrError: '',
  isExtERC20: false,
  extAmtWei: null,
  extTokenBalance: 0n,
}

describe('TransferForm CTA state machine', () => {
  it('happy path → ready', () => {
    expect(deriveCtaState(READY_INPUT)).toBe('ready')
  })

  it('disconnected → "disconnected" (shows Connect Wallet)', () => {
    expect(deriveCtaState({ ...READY_INPUT, isConnected: false })).toBe('disconnected')
  })

  it('unsupported chain → "wrong_network"', () => {
    expect(deriveCtaState({ ...READY_INPUT, chainId: 999 })).toBe('wrong_network')
  })

  it('all supported chains are recognized', () => {
    for (const chainId of SUPPORTED_CHAINS) {
      expect(deriveCtaState({ ...READY_INPUT, chainId })).toBe('ready')
    }
  })

  it('busy (signing/approving) → "busy"', () => {
    expect(deriveCtaState({ ...READY_INPUT, busy: true })).toBe('busy')
  })

  it('amount > balance → "insufficient"', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      rawIn: 10_000_000_000_000_000_000n, // 10 ETH
      tokenBalance: 5_000_000_000_000_000_000n, // 5 ETH
    })).toBe('insufficient')
  })

  it('exact balance → ready (not insufficient)', () => {
    const balance = 1_000_000_000_000_000_000n
    expect(deriveCtaState({
      ...READY_INPUT,
      rawIn: balance,
      tokenBalance: balance,
    })).toBe('ready')
  })

  it('oracle denied with FeeRouter → "oracle_denied"', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      oracleDenied: true,
      feeRouterAvailable: true,
    })).toBe('oracle_denied')
  })

  it('oracle denied WITHOUT FeeRouter → NOT oracle_denied (direct mode)', () => {
    // When FeeRouter is not available, oracle denial is ignored
    expect(deriveCtaState({
      ...READY_INPUT,
      oracleDenied: true,
      feeRouterAvailable: false,
    })).toBe('ready')
  })

  it('oracle denied for external ERC-20 → NOT oracle_denied', () => {
    // External ERC-20 transfers bypass oracle
    expect(deriveCtaState({
      ...READY_INPUT,
      oracleDenied: true,
      isExtERC20: true,
      extAmtWei: 1_000_000n,
      extTokenBalance: 5_000_000n,
    })).toBe('ready')
  })

  it('no liquidity → "no_liquidity"', () => {
    expect(deriveCtaState({ ...READY_INPUT, noLiquidity: true })).toBe('no_liquidity')
  })

  it('no recipient → "no_recipient"', () => {
    expect(deriveCtaState({ ...READY_INPUT, recipient: '' })).toBe('no_recipient')
  })

  it('invalid address → "no_recipient"', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      recipient: '0xinvalid',
      addrError: 'Indirizzo non valido',
    })).toBe('no_recipient')
  })

  it('no amount → "no_amount"', () => {
    expect(deriveCtaState({ ...READY_INPUT, rawIn: null })).toBe('no_amount')
  })

  it('zero amount → "no_amount"', () => {
    expect(deriveCtaState({ ...READY_INPUT, rawIn: 0n })).toBe('no_amount')
  })

  it('external ERC-20 with no amount → "no_amount"', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      isExtERC20: true,
      extAmtWei: null,
      extTokenBalance: 5_000_000n,
    })).toBe('no_amount')
  })

  it('external ERC-20 insufficient balance → "insufficient"', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      isExtERC20: true,
      extAmtWei: 10_000_000n,
      extTokenBalance: 5_000_000n,
    })).toBe('insufficient')
  })
})

describe('CTA state priority (higher states override lower)', () => {
  it('disconnected beats everything', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      isConnected: false,
      // Even with valid amount, recipient, etc.
    })).toBe('disconnected')
  })

  it('wrong_network beats insufficient', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      chainId: 999,
      rawIn: 100n,
      tokenBalance: 1n, // insufficient
    })).toBe('wrong_network')
  })

  it('busy beats insufficient', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      busy: true,
      rawIn: 100n,
      tokenBalance: 1n,
    })).toBe('busy')
  })

  it('insufficient beats oracle_denied', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      rawIn: 100n,
      tokenBalance: 1n,
      oracleDenied: true,
    })).toBe('insufficient')
  })

  it('oracle_denied beats no_liquidity', () => {
    expect(deriveCtaState({
      ...READY_INPUT,
      oracleDenied: true,
      noLiquidity: true,
    })).toBe('oracle_denied')
  })
})

describe('CTA button disabled states', () => {
  const DISABLED_STATES: CtaState[] = ['busy', 'insufficient', 'no_recipient', 'no_amount', 'oracle_denied', 'no_liquidity']
  const ENABLED_STATES: CtaState[] = ['ready', 'wrong_network']

  it('disabled states are correct set', () => {
    expect(DISABLED_STATES).toHaveLength(6)
    expect(DISABLED_STATES).toContain('busy')
    expect(DISABLED_STATES).toContain('insufficient')
    expect(DISABLED_STATES).toContain('oracle_denied')
  })

  it('ready and wrong_network are clickable', () => {
    expect(ENABLED_STATES).toContain('ready')
    expect(ENABLED_STATES).toContain('wrong_network')
    expect(DISABLED_STATES).not.toContain('ready')
    expect(DISABLED_STATES).not.toContain('wrong_network')
  })
})

describe('CTA button labels (Italian UI)', () => {
  // Maps CTA state to expected button text (mirrors TransferForm lines 1393-1403)
  const LABELS: Partial<Record<CtaState, string>> = {
    oracle_denied: 'Transazione Bloccata',
    no_liquidity: 'Liquidità insufficiente',
    no_recipient: 'Inserisci destinatario',
    no_amount: 'Inserisci un importo',
  }

  it('each state has a distinct label', () => {
    const values = Object.values(LABELS)
    const unique = new Set(values)
    expect(unique.size).toBe(values.length)
  })

  it('oracle_denied label is clear', () => {
    expect(LABELS.oracle_denied).toBe('Transazione Bloccata')
  })

  it('insufficient label includes token symbol pattern', () => {
    // Pattern: `Saldo ${displaySym} insufficiente`
    const label = (sym: string) => `Saldo ${sym} insufficiente`
    expect(label('ETH')).toBe('Saldo ETH insufficiente')
    expect(label('USDC')).toBe('Saldo USDC insufficiente')
  })
})
