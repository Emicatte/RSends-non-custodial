/**
 * Unit tests — Logger sanitization
 *
 * The logger must NEVER leak sensitive data (private keys, signatures, API keys)
 * to console output, even in development mode.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── Re-implement sanitize from lib/logger.ts (not exported) ────────

const SENSITIVE_KEYS = [
  'oracleSignature', 'signature', 'sig', 'privateKey', 'private_key',
  'secret', 'hmac', 'apiKey', 'api_key', 'password', 'seed',
]

function sanitize(data: Record<string, unknown>): Record<string, unknown> {
  const sanitized = { ...data }
  for (const key of Object.keys(sanitized)) {
    if (SENSITIVE_KEYS.some(s => key.toLowerCase().includes(s.toLowerCase()))) {
      sanitized[key] = '[REDACTED]'
    }
    if (typeof sanitized[key] === 'string') {
      const val = sanitized[key] as string
      if (val.startsWith('0x') && val.length > 20) {
        sanitized[key] = `${val.slice(0, 10)}...${val.slice(-6)}`
      }
    }
  }
  return sanitized
}

describe('logger sanitize', () => {
  it('redacts oracleSignature', () => {
    const data = { oracleSignature: '0xdeadbeef1234567890' }
    const s = sanitize(data)
    expect(s.oracleSignature).toBe('[REDACTED]')
  })

  it('redacts privateKey', () => {
    const s = sanitize({ privateKey: '0xabcdef1234567890abcdef' })
    expect(s.privateKey).toBe('[REDACTED]')
  })

  it('redacts api_key', () => {
    const s = sanitize({ api_key: 'sk-1234567890' })
    expect(s.api_key).toBe('[REDACTED]')
  })

  it('redacts hmac secret', () => {
    const s = sanitize({ hmacSecret: 'super-secret-value' })
    expect(s.hmacSecret).toBe('[REDACTED]')
  })

  it('redacts password', () => {
    const s = sanitize({ password: 'hunter2' })
    expect(s.password).toBe('[REDACTED]')
  })

  it('redacts seed phrase', () => {
    const s = sanitize({ seed: 'abandon abandon abandon...' })
    expect(s.seed).toBe('[REDACTED]')
  })

  it('truncates long 0x strings (hashes, addresses)', () => {
    const txHash = '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef'
    const s = sanitize({ txHash })
    expect(s.txHash).toBe('0x12345678...abcdef')
    // Not the full hash
    expect((s.txHash as string).length).toBeLessThan(txHash.length)
  })

  it('leaves short 0x strings unchanged', () => {
    const s = sanitize({ value: '0x1234' })
    expect(s.value).toBe('0x1234')
  })

  it('preserves non-sensitive string values', () => {
    const s = sanitize({ module: 'TransferForm', action: 'send' })
    expect(s.module).toBe('TransferForm')
    expect(s.action).toBe('send')
  })

  it('preserves numeric values', () => {
    const s = sanitize({ chainId: 8453, amount: 100 })
    expect(s.chainId).toBe(8453)
    expect(s.amount).toBe(100)
  })

  it('case-insensitive key matching', () => {
    const s = sanitize({ ORACLESIGNATURE: '0xfoo', ApiKey: 'bar' })
    expect(s.ORACLESIGNATURE).toBe('[REDACTED]')
    expect(s.ApiKey).toBe('[REDACTED]')
  })

  it('does not mutate original object', () => {
    const original = { privateKey: 'secret123', chainId: 1 }
    const s = sanitize(original)
    expect(original.privateKey).toBe('secret123')
    expect(s.privateKey).toBe('[REDACTED]')
  })
})
