'use client'

import type { TokenMarket } from '@/lib/types/tokenMarket'
import AnimatedNumber from '@/components/motion/AnimatedNumber'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import { useCallback } from 'react'

const TOP_IDS = ['bitcoin', 'ethereum', 'tron', 'binancecoin', 'usd-coin']

const TOKEN_META: Record<string, { name: string; symbol: string }> = {
  bitcoin:      { name: 'Bitcoin',    symbol: 'BTC' },
  ethereum:     { name: 'Ethereum',   symbol: 'ETH' },
  tron:         { name: 'TRON',       symbol: 'TRX' },
  binancecoin:  { name: 'BNB',        symbol: 'BNB' },
  'usd-coin':   { name: 'USD Coin',   symbol: 'USDC' },
}

function formatPrice(v: number): string {
  if (v >= 100) return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (v >= 0.01) return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 })
}

type Props = {
  data: Record<string, TokenMarket>
  loading: boolean
  tilt?: boolean
}

function TokenLogo({ image, symbol, size = 32 }: { image: string | null; symbol: string; size?: number }) {
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

export default function IPhoneMockup({ data, loading, tilt = true }: Props) {
  const fmt = useCallback(formatPrice, [])

  const tokens = TOP_IDS.map(id => ({
    id,
    meta: TOKEN_META[id],
    market: data[id],
  })).filter(t => t.market)

  return (
    <div style={{
      width: 320, height: 650,
      transform: tilt ? 'perspective(1200px) rotateY(-8deg) rotateX(2deg) rotateZ(-2deg)' : 'none',
      transformStyle: 'preserve-3d' as const,
      position: 'relative',
    }}>
      {/* Drop shadow */}
      <div style={{
        position: 'absolute', inset: 0, borderRadius: 56,
        background: '#0A0A0A',
        transform: 'translate(14px, 20px)',
        filter: 'blur(28px)',
        opacity: 0.22,
      }} />

      {/* Phone body */}
      <div style={{
        position: 'relative', width: '100%', height: '100%',
        borderRadius: 56, overflow: 'hidden',
        background: 'linear-gradient(145deg, #1a1a1a 0%, #0A0A0A 100%)',
        padding: 10,
        boxShadow: '0 0 0 2px #2a2a2a inset',
      }}>
        {/* Screen */}
        <div style={{
          width: '100%', height: '100%',
          borderRadius: 46, overflow: 'hidden',
          position: 'relative',
          background: '#FAFAFA',
        }}>
          {/* Notch */}
          <div style={{
            position: 'absolute', left: '50%', transform: 'translateX(-50%)',
            top: 8, zIndex: 10,
            width: 110, height: 28,
            background: '#0A0A0A',
            borderRadius: 18,
          }} />

          {/* Status bar */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '12px 24px 0',
            fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text,
          }}>
            <span>9:41</span>
            <span style={{ opacity: 0 }}>.</span>
            <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
              {/* Signal bars */}
              {[4, 6, 8, 10].map((h, i) => (
                <div key={i} style={{
                  width: 3, height: h, borderRadius: 1,
                  background: C.text, opacity: i < 3 ? 1 : 0.3,
                }} />
              ))}
              <div style={{ width: 6 }} />
              {/* Battery */}
              <div style={{
                width: 20, height: 10, borderRadius: 3,
                border: `1.5px solid ${C.text}`,
                padding: 1.5, position: 'relative',
              }}>
                <div style={{
                  width: '75%', height: '100%', borderRadius: 1,
                  background: C.text,
                }} />
              </div>
            </div>
          </div>

          {/* App content */}
          <div style={{ padding: '44px 20px 0' }}>
            <div style={{
              fontFamily: C.D, fontSize: 11, fontWeight: 600,
              color: C.purple, letterSpacing: '0.15em',
              textTransform: 'uppercase' as const, marginBottom: 6,
            }}>
              RSENDS
            </div>
            <h3 style={{
              fontFamily: C.D, fontSize: 24, fontWeight: 600,
              color: C.text, margin: '0 0 20px',
            }}>
              Markets
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {tokens.map((t, i) => {
                const m = t.market
                const positive = (m.change24h ?? 0) >= 0
                return (
                  <Link
                    key={t.id}
                    href={`/token/${t.id}`}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '12px 8px', margin: '0 -8px',
                      borderBottom: i < tokens.length - 1 ? `1px solid rgba(10,10,10,0.06)` : 'none',
                      borderRadius: 10,
                      textDecoration: 'none',
                      color: 'inherit',
                      transition: 'background 0.15s',
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,10,10,0.04)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <TokenLogo image={m.image} symbol={t.meta.symbol} size={32} />
                      <div>
                        <div style={{
                          fontFamily: C.D, fontSize: 14, fontWeight: 500, color: C.text,
                        }}>
                          {t.meta.name}
                        </div>
                        <div style={{
                          fontFamily: C.D, fontSize: 11, color: C.sub,
                          textTransform: 'uppercase' as const,
                        }}>
                          {t.meta.symbol}
                        </div>
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontFamily: C.M, fontSize: 14, fontWeight: 600, color: C.text }}>
                        {m.price != null ? (
                          <AnimatedNumber value={m.price} format={fmt} />
                        ) : '—'}
                      </div>
                      <div style={{
                        fontFamily: C.M, fontSize: 11, fontWeight: 600,
                        color: positive ? '#0E9F6E' : '#D4342E',
                      }}>
                        {m.change24h != null ? (
                          <>
                            {positive ? '▲' : '▼'}{' '}
                            {Math.abs(m.change24h).toFixed(2)}%
                          </>
                        ) : '—'}
                      </div>
                    </div>
                  </Link>
                )
              })}
            </div>
          </div>

          {/* Home indicator */}
          <div style={{
            position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
            width: 134, height: 5, borderRadius: 3, background: 'rgba(10,10,10,0.2)',
          }} />
        </div>
      </div>
    </div>
  )
}
