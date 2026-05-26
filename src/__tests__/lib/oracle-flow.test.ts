/**
 * Unit tests — Oracle flow (EIP-712 domain, nonce format, deadline, risk scoring)
 *
 * Tests the ALGORITHM and data structures, not the actual crypto signing
 * (which requires a private key and is tested in integration).
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { checkRateLimit, __resetRateLimits } from '@/lib/rateLimit'

// ── Re-implement pure functions from oracle/sign/route.ts ──────────

function getDomainConfig(chainId: number) {
  if (chainId === 84532) {
    return { name: 'FeeRouterV3' as const, version: '3' as const, isV3: true }
  }
  return { name: 'FeeRouterV4' as const, version: '4' as const, isV3: false }
}

const ORACLE_TYPES_V3 = {
  OracleApproval: [
    { name: 'sender',    type: 'address' },
    { name: 'recipient', type: 'address' },
    { name: 'token',     type: 'address' },
    { name: 'amount',    type: 'uint256' },
    { name: 'nonce',     type: 'bytes32' },
    { name: 'deadline',  type: 'uint256' },
  ],
} as const

const ORACLE_TYPES_V4 = {
  OracleApproval: [
    { name: 'sender',    type: 'address' },
    { name: 'recipient', type: 'address' },
    { name: 'tokenIn',   type: 'address' },
    { name: 'tokenOut',  type: 'address' },
    { name: 'amountIn',  type: 'uint256' },
    { name: 'nonce',     type: 'bytes32' },
    { name: 'deadline',  type: 'uint256' },
  ],
} as const

const EUR_RATES: Record<string, number> = {
  ETH: 2200, USDC: 0.92, USDT: 0.92, EURC: 1.0,
  CBBTC: 88000, WBTC: 88000, DEGEN: 0.003,
}

const BLACKLIST = new Set([
  '0x722122df12d4e14e13ac3b6895a86e84145b6967',
  '0xd90e2f925da726b50c4ed8d0fb90ad053324f31b',
])

function computeRiskScore(eurValue: number): { riskScore: number; riskLevel: string } {
  let riskScore = 5
  if (eurValue > 50_000) riskScore = 35
  else if (eurValue > 10_000) riskScore = 20
  else if (eurValue > 5_000) riskScore = 10
  const riskLevel = riskScore >= 80 ? 'BLOCKED' : riskScore >= 60 ? 'HIGH' : riskScore >= 30 ? 'MEDIUM' : 'LOW'
  return { riskScore, riskLevel }
}

describe('getDomainConfig — EIP-712 domain per chain', () => {
  it('Base Sepolia (84532) → V3', () => {
    const cfg = getDomainConfig(84532)
    expect(cfg.name).toBe('FeeRouterV3')
    expect(cfg.version).toBe('3')
    expect(cfg.isV3).toBe(true)
  })

  it('Base Mainnet (8453) → V4', () => {
    const cfg = getDomainConfig(8453)
    expect(cfg.name).toBe('FeeRouterV4')
    expect(cfg.version).toBe('4')
    expect(cfg.isV3).toBe(false)
  })

  it('Ethereum (1) → V4', () => {
    const cfg = getDomainConfig(1)
    expect(cfg.name).toBe('FeeRouterV4')
    expect(cfg.version).toBe('4')
    expect(cfg.isV3).toBe(false)
  })

  it('unknown chain → V4 (default)', () => {
    const cfg = getDomainConfig(999)
    expect(cfg.isV3).toBe(false)
  })
})

describe('EIP-712 type structures', () => {
  it('V3 has 6 fields (token, amount)', () => {
    expect(ORACLE_TYPES_V3.OracleApproval).toHaveLength(6)
    const names = ORACLE_TYPES_V3.OracleApproval.map(f => f.name)
    expect(names).toContain('token')
    expect(names).toContain('amount')
    expect(names).not.toContain('tokenIn')
  })

  it('V4 has 7 fields (tokenIn, tokenOut, amountIn)', () => {
    expect(ORACLE_TYPES_V4.OracleApproval).toHaveLength(7)
    const names = ORACLE_TYPES_V4.OracleApproval.map(f => f.name)
    expect(names).toContain('tokenIn')
    expect(names).toContain('tokenOut')
    expect(names).toContain('amountIn')
    expect(names).not.toContain('token')
  })

  it('both versions share sender, recipient, nonce, deadline', () => {
    const v3Names = ORACLE_TYPES_V3.OracleApproval.map(f => f.name)
    const v4Names = ORACLE_TYPES_V4.OracleApproval.map(f => f.name)
    for (const shared of ['sender', 'recipient', 'nonce', 'deadline']) {
      expect(v3Names).toContain(shared)
      expect(v4Names).toContain(shared)
    }
  })
})

describe('nonce format', () => {
  it('generated nonce is 0x + 64 hex chars (32 bytes)', () => {
    // Simulate what the oracle does
    const bytes = new Uint8Array(32)
    globalThis.crypto.getRandomValues(bytes)
    const nonce = '0x' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('')
    expect(nonce).toMatch(/^0x[0-9a-f]{64}$/)
  })
})

describe('deadline calculation', () => {
  it('deadline is 20 minutes (1200 seconds) in the future', () => {
    const now = Math.floor(Date.now() / 1000)
    const deadline = BigInt(now + 1200)
    const diff = Number(deadline) - now
    expect(diff).toBe(1200)
  })

  it('deadline is always a positive bigint', () => {
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 1200)
    expect(deadline).toBeGreaterThan(0n)
  })
})

describe('AML blacklist check', () => {
  it('blocks known Tornado Cash address', () => {
    expect(BLACKLIST.has('0x722122df12d4e14e13ac3b6895a86e84145b6967')).toBe(true)
  })

  it('allows clean address', () => {
    expect(BLACKLIST.has('0x1234567890abcdef1234567890abcdef12345678')).toBe(false)
  })
})

describe('risk scoring', () => {
  it('small tx (< 5000 EUR) → LOW, score 5', () => {
    const r = computeRiskScore(100)
    expect(r.riskScore).toBe(5)
    expect(r.riskLevel).toBe('LOW')
  })

  it('medium tx (5000-10000 EUR) → LOW, score 10', () => {
    const r = computeRiskScore(7000)
    expect(r.riskScore).toBe(10)
    expect(r.riskLevel).toBe('LOW')
  })

  it('large tx (10000-50000 EUR) → LOW, score 20', () => {
    const r = computeRiskScore(25000)
    expect(r.riskScore).toBe(20)
    expect(r.riskLevel).toBe('LOW')
  })

  it('very large tx (> 50000 EUR) → MEDIUM, score 35', () => {
    const r = computeRiskScore(100000)
    expect(r.riskScore).toBe(35)
    expect(r.riskLevel).toBe('MEDIUM')
  })

  it('EUR rate for ETH is 2200', () => {
    const eurValue = 1 * EUR_RATES['ETH']
    expect(eurValue).toBe(2200)
  })
})

describe('per-IP rate limit (lib/rateLimit)', () => {
  beforeEach(() => __resetRateLimits())

  it('allows up to max requests within window', () => {
    const ip = '1.2.3.4'
    for (let i = 0; i < 10; i++) {
      expect(
        checkRateLimit(ip, { max: 10, windowMs: 60_000, key: 't1' }).allowed,
      ).toBe(true)
    }
  })

  it('blocks the (max+1)-th request from the same IP and returns retryAfter', () => {
    const ip = '1.2.3.4'
    for (let i = 0; i < 10; i++) {
      checkRateLimit(ip, { max: 10, windowMs: 60_000, key: 't2' })
    }
    const r = checkRateLimit(ip, { max: 10, windowMs: 60_000, key: 't2' })
    expect(r.allowed).toBe(false)
    expect(r.retryAfter).toBeGreaterThanOrEqual(1)
    expect(r.retryAfter).toBeLessThanOrEqual(60)
  })

  it('different IPs have independent quotas', () => {
    for (let i = 0; i < 10; i++) {
      checkRateLimit('1.1.1.1', { max: 10, windowMs: 60_000, key: 't3' })
    }
    expect(
      checkRateLimit('1.1.1.1', { max: 10, windowMs: 60_000, key: 't3' }).allowed,
    ).toBe(false)
    expect(
      checkRateLimit('2.2.2.2', { max: 10, windowMs: 60_000, key: 't3' }).allowed,
    ).toBe(true)
  })

  it('namespaces (key) isolate limiters', () => {
    for (let i = 0; i < 10; i++) {
      checkRateLimit('1.1.1.1', { max: 10, windowMs: 60_000, key: 'ns-a' })
    }
    expect(
      checkRateLimit('1.1.1.1', { max: 10, windowMs: 60_000, key: 'ns-a' }).allowed,
    ).toBe(false)
    expect(
      checkRateLimit('1.1.1.1', { max: 10, windowMs: 60_000, key: 'ns-b' }).allowed,
    ).toBe(true)
  })
})
