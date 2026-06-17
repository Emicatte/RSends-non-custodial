'use client'

import { useId, useCallback } from 'react'
import type { TokenMarket } from '@/lib/types/tokenMarket'
import AnimatedNumber from '@/components/motion/AnimatedNumber'
import { useRouter } from '@/i18n/navigation'
import { C } from '@/app/designTokens'

const TOP_IDS = [
  'bitcoin', 'ethereum', 'tron', 'binancecoin',
  'usd-coin', 'tether', 'avalanche-2',
]

const TOKEN_META: Record<string, { name: string; symbol: string }> = {
  bitcoin:         { name: 'Bitcoin',     symbol: 'BTC' },
  ethereum:        { name: 'Ethereum',    symbol: 'ETH' },
  tron:            { name: 'TRON',        symbol: 'TRX' },
  binancecoin:     { name: 'BNB',         symbol: 'BNB' },
  'usd-coin':      { name: 'USD Coin',    symbol: 'USDC' },
  tether:          { name: 'Tether',      symbol: 'USDT' },
  'avalanche-2':   { name: 'Avalanche',   symbol: 'AVAX' },
}

function formatPrice(v: number): string {
  if (v >= 100) return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (v >= 0.01) return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 })
}

function formatVolume(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  return `$${(v / 1_000).toFixed(0)}K`
}

// ── Sparkline (Catmull-Rom) ───────────────────────────────────────────────

function Sparkline({ data, positive, id }: { data: number[]; positive: boolean; id: string }) {
  if (!data || data.length < 2) return <div style={{ width: 80, height: 24 }} />

  const w = 80
  const h = 24
  const PAD = 2

  // Downsample if too many points
  const sampled = data.length > 60
    ? data.filter((_, i) => i % Math.ceil(data.length / 50) === 0)
    : data

  const min = Math.min(...sampled)
  const max = Math.max(...sampled)
  const range = max - min || 1

  const pts = sampled.map((v, i) => ({
    x: (i / (sampled.length - 1)) * w,
    y: PAD + (1 - (v - min) / range) * (h - PAD * 2),
  }))

  // Catmull-Rom to cubic bezier
  let d = `M ${pts[0].x.toFixed(2)},${pts[0].y.toFixed(2)}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[Math.min(i + 2, pts.length - 1)]

    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6

    d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`
  }

  const color = positive ? C.green : C.red
  const fillPath = `${d} L ${w.toFixed(2)},${h.toFixed(2)} L 0,${h.toFixed(2)} Z`
  const gid = `spark-${id}`

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }} aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.18} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={fillPath} fill={`url(#${gid})`} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Token logo ────────────────────────────────────────────────────────────

function TokenLogo({ image, symbol, size = 24 }: { image: string | null; symbol: string; size?: number }) {
  if (!image) {
    return (
      <div style={{
        width: size, height: size, borderRadius: '50%',
        background: `linear-gradient(135deg, ${C.purple}, #e8825c)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: C.D, fontSize: Math.round(size * 0.42), fontWeight: 700, color: '#fff',
        flexShrink: 0,
      }}>
        {symbol.slice(0, 1)}
      </div>
    )
  }
  return (
    <img
      src={image}
      alt={symbol}
      width={size}
      height={size}
      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      style={{ width: size, height: size, borderRadius: '50%', flexShrink: 0, display: 'block', objectFit: 'cover' }}
    />
  )
}

// ── Main component ────────────────────────────────────────────────────────

type Props = {
  data: Record<string, TokenMarket>
  loading: boolean
}

export default function DesktopMockup({ data, loading }: Props) {
  const router = useRouter()
  const baseId = useId()
  const fmt = useCallback(formatPrice, [])

  const tokens = TOP_IDS.map(id => ({
    id,
    meta: TOKEN_META[id],
    market: data[id],
  })).filter(t => t.market)

  const HEADERS = ['Token', 'Price', '24h', 'Volume', '7d']

  return (
    <div style={{
      width: 720,
      transform: 'perspective(1400px) rotateY(6deg) rotateX(4deg) rotateZ(1deg)',
      transformStyle: 'preserve-3d' as const,
      position: 'relative',
    }}>
      {/* Shadow */}
      <div style={{
        position: 'absolute', inset: 0, borderRadius: 12,
        background: '#0A0A0A',
        transform: 'translate(-18px, 24px)',
        filter: 'blur(32px)',
        opacity: 0.18,
      }} />

      {/* Browser frame — clickable → /markets */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => router.push('/markets')}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') router.push('/markets') }}
        onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 24px rgba(200,81,44,0.12)' }}
        onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.04)' }}
        style={{
          position: 'relative', borderRadius: 12, overflow: 'hidden',
          background: '#fff',
          border: `1px solid ${C.border}`,
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          cursor: 'pointer',
          transition: 'box-shadow 0.2s ease',
        }}
      >
        {/* Browser chrome */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '12px 16px',
          borderBottom: `1px solid rgba(10,10,10,0.08)`,
          background: '#FAFAFA',
        }}>
          {/* Traffic lights */}
          <div style={{ display: 'flex', gap: 6 }}>
            {['#FF5F57', '#FEBC2E', '#28C840'].map(color => (
              <div key={color} style={{ width: 12, height: 12, borderRadius: '50%', background: color }} />
            ))}
          </div>

          {/* URL bar */}
          <div style={{ flex: 1, margin: '0 16px' }}>
            <div style={{
              maxWidth: 380, margin: '0 auto',
              borderRadius: 6, padding: '5px 12px',
              fontSize: 12, color: C.sub,
              background: '#fff',
              border: `1px solid ${C.border}`,
              textAlign: 'center',
              fontFamily: C.D,
            }}>
              rsends.io/app
            </div>
          </div>

          <div style={{ width: 52 }} />
        </div>

        {/* App content */}
        <div style={{ padding: '28px 32px 24px' }}>
          {/* Content header */}
          <div style={{
            display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
            marginBottom: 20,
          }}>
            <div>
              <div style={{
                fontFamily: C.D, fontSize: 11, fontWeight: 600,
                color: C.purple, letterSpacing: '0.18em',
                textTransform: 'uppercase' as const, marginBottom: 4,
              }}>
                RSENDS / MARKETS
              </div>
              <h3 style={{
                fontFamily: C.D, fontSize: 20, fontWeight: 600,
                color: C.text, margin: 0,
              }}>
                Tokens overview
              </h3>
            </div>
            <div style={{
              fontFamily: C.M, fontSize: 11, color: C.sub,
            }}>
              Live &middot; updates every 30s
            </div>
          </div>

          {/* Table */}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(10,10,10,0.08)' }}>
                {HEADERS.map(h => (
                  <th key={h} style={{
                    fontFamily: C.D, fontSize: 10, fontWeight: 600,
                    color: 'rgba(10,10,10,0.60)',
                    letterSpacing: '0.12em', textTransform: 'uppercase' as const,
                    padding: '0 0 10px', textAlign: h === 'Token' ? 'left' : 'right',
                    whiteSpace: 'nowrap' as const,
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tokens.map((t, i) => {
                const m = t.market
                const positive = (m.change24h ?? 0) >= 0
                return (
                  <tr key={t.id} style={{
                    borderBottom: i < tokens.length - 1 ? '1px solid rgba(10,10,10,0.04)' : 'none',
                  }}>
                    {/* Token */}
                    <td style={{ padding: '12px 0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <TokenLogo image={m.image} symbol={t.meta.symbol} size={24} />
                        <div>
                          <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 500, color: C.text }}>
                            {t.meta.name}
                          </div>
                          <div style={{
                            fontFamily: C.D, fontSize: 10, color: C.sub,
                            textTransform: 'uppercase' as const,
                          }}>
                            {t.meta.symbol}
                          </div>
                        </div>
                      </div>
                    </td>
                    {/* Price */}
                    <td style={{
                      padding: '12px 0', textAlign: 'right',
                      fontFamily: C.M, fontSize: 13, fontWeight: 600, color: C.text,
                    }}>
                      {m.price != null ? (
                        <AnimatedNumber value={m.price} format={fmt} />
                      ) : '—'}
                    </td>
                    {/* 24h */}
                    <td style={{
                      padding: '12px 0', textAlign: 'right',
                      fontFamily: C.M, fontSize: 13, fontWeight: 600,
                      color: positive ? '#0E9F6E' : '#D4342E',
                    }}>
                      {m.change24h != null ? (
                        <>
                          {positive ? '▲' : '▼'}{' '}
                          {Math.abs(m.change24h).toFixed(2)}%
                        </>
                      ) : '—'}
                    </td>
                    {/* Volume */}
                    <td style={{
                      padding: '12px 0', textAlign: 'right',
                      fontFamily: C.M, fontSize: 13, color: 'rgba(10,10,10,0.70)',
                    }}>
                      {formatVolume(m.volume)}
                    </td>
                    {/* Sparkline */}
                    <td style={{ padding: '12px 0', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex' }}>
                        <Sparkline
                          data={m.sparkline}
                          positive={positive}
                          id={`${baseId}-${t.id}`}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
