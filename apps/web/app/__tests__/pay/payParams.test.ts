import { getAddress, stringToHex, parseUnits } from 'viem'
import {
  parsePayParams, encodeRef, deriveInvoiceId, buildPayUrl,
} from '@/lib/web3/payParams'

const MERCHANT = '0x758A37F88D684e31D5a698514142f02A1bDD2c04'

describe('encodeRef', () => {
  it('encodes a short ref as right-padded ascii bytes32 (legible in BaseScan)', () => {
    expect(encodeRef('order-42')).toBe(stringToHex('order-42', { size: 32 }))
  })

  it('hashes a ref longer than 31 bytes', () => {
    const long = 'x'.repeat(40)
    const out = encodeRef(long)
    expect(out).toMatch(/^0x[0-9a-f]{64}$/)
    expect(out).not.toBe(stringToHex(long.slice(0, 31), { size: 32 }))
  })

  it('throws on empty ref', () => {
    expect(() => encodeRef('  ')).toThrow()
  })
})

describe('deriveInvoiceId', () => {
  it('uses encodeRef when a ref is present', () => {
    const id = deriveInvoiceId('order-42', getAddress(MERCHANT), getAddress(MERCHANT), 1n)
    expect(id).toBe(stringToHex('order-42', { size: 32 }))
  })

  it('is deterministic and stable when ref is absent', () => {
    const a = deriveInvoiceId(undefined, getAddress(MERCHANT), getAddress(MERCHANT), 100000000n)
    const b = deriveInvoiceId(undefined, getAddress(MERCHANT), getAddress(MERCHANT), 100000000n)
    expect(a).toBe(b)
    expect(a).toMatch(/^0x[0-9a-f]{64}$/)
  })
})

describe('parsePayParams', () => {
  it('parses a valid USDC request (amount in token base units, checksummed merchant)', () => {
    const r = parsePayParams({ token: 'USDC', amount: '100', to: MERCHANT, ref: 'order-42' })
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.request.amountBaseUnits).toBe(parseUnits('100', 6))
    expect(r.request.amountBaseUnits).toBe(100000000n)
    expect(r.request.merchant).toBe(getAddress(MERCHANT))
    expect(r.request.ref).toBe('order-42')
    expect(r.request.invoiceId).toBe(stringToHex('order-42', { size: 32 }))
  })

  it('rejects a disabled token (EURC) as not available', () => {
    const r = parsePayParams({ token: 'EURC', amount: '100', to: MERCHANT })
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.error).toMatch(/available/i)
  })

  it('rejects unknown token', () => {
    const r = parsePayParams({ token: 'DOGE', amount: '100', to: MERCHANT })
    expect(r.ok).toBe(false)
  })

  it('rejects invalid / missing amount', () => {
    expect(parsePayParams({ token: 'USDC', amount: 'abc', to: MERCHANT }).ok).toBe(false)
    expect(parsePayParams({ token: 'USDC', amount: '', to: MERCHANT }).ok).toBe(false)
    expect(parsePayParams({ token: 'USDC', amount: '0', to: MERCHANT }).ok).toBe(false)
  })

  it('rejects amount below the token minimum', () => {
    const r = parsePayParams({ token: 'USDC', amount: '0.001', to: MERCHANT })
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.error).toMatch(/minimum/i)
  })

  it('rejects invalid merchant address', () => {
    expect(parsePayParams({ token: 'USDC', amount: '100', to: '0xnothex' }).ok).toBe(false)
    expect(parsePayParams({ token: 'USDC', amount: '100', to: '' }).ok).toBe(false)
  })
})

describe('buildPayUrl', () => {
  it('builds a link that parsePayParams round-trips', () => {
    const url = buildPayUrl({ token: 'USDC', amount: '100', to: MERCHANT, ref: 'order-42' })
    expect(url.startsWith('/pay?')).toBe(true)
    const qs = new URLSearchParams(url.split('?')[1])
    const r = parsePayParams({
      token: qs.get('token'), amount: qs.get('amount'), to: qs.get('to'), ref: qs.get('ref'),
    })
    expect(r.ok).toBe(true)
  })

  it('omits ref when not provided', () => {
    const url = buildPayUrl({ token: 'USDC', amount: '5', to: MERCHANT })
    expect(url).not.toMatch(/ref=/)
  })
})
