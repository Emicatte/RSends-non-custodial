/**
 * app/TokenDetailView.tsx — Uniswap-style token detail view
 *
 * Inline expansion triggered by clicking a row in ExploreTokens.
 * Reuses the same palette + chart math. Not a separate route.
 */
'use client'

import { useMemo, useRef, useState } from 'react'
import { TOKEN_LIST, SUPPORTED_CHAINS, type ChainId } from './tokens/tokenRegistry'
import type { TokenMarket } from '@/lib/types/tokenMarket'
import { C } from '@/app/designTokens'

const CHAIN_COLORS = [
  '#627EEA', '#F3BA2F', '#8247E5', '#E84142',
  '#28A0F0', '#FCFF52', '#FF0420', '#FF3B30', '#25292E',
]

const CHAIN_ICONS: Record<number, string> = {
  1:     'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
  10:    'https://assets.coingecko.com/coins/images/25244/small/Optimism.png',
  56:    'https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png',
  137:   'https://assets.coingecko.com/coins/images/4713/small/polygon.png',
  324:   'https://assets.coingecko.com/asset_platforms/images/121/small/zksync.jpeg',
  8453:  'https://assets.coingecko.com/asset_platforms/images/131/small/base.jpeg',
  42161: 'https://assets.coingecko.com/coins/images/16547/small/arb.jpg',
  42220: 'https://assets.coingecko.com/coins/images/11090/small/InjXBNx9_400x400.jpg',
  43114: 'https://assets.coingecko.com/coins/images/12559/small/Avalanche_Circle_RedWhite_Trans.png',
  81457: 'https://assets.coingecko.com/asset_platforms/images/177/small/blast.jpeg',
  84532: 'https://assets.coingecko.com/asset_platforms/images/131/small/base.jpeg',
  728126428: 'https://assets.coingecko.com/coins/images/1094/small/tron-logo.png',
}

interface Props {
  coingeckoId: string
  market: TokenMarket | undefined
  marketLoading: boolean
  onBack: () => void
  isMobile: boolean
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatUsd(v: number | null | undefined): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '—'
  let maxFrac: number
  if (v >= 100) maxFrac = 2
  else if (v >= 1) maxFrac = 4
  else if (v >= 0.01) maxFrac = 4
  else maxFrac = 6
  return v.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: maxFrac,
  })
}

function formatCompactUsd(v: number | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(2)}K`
  return `$${v.toFixed(2)}`
}

function truncateAddr(a: string): string {
  return a.length > 10 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a
}

// Catmull-Rom → cubic bezier — matches Sparkline math, without downsampling.
function buildSmoothPath(data: number[], width: number, height: number) {
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const PAD_Y = 8

  const pts = data.map((v, i) => ({
    x: (i / (data.length - 1)) * width,
    y: PAD_Y + (1 - (v - min) / range) * (height - PAD_Y * 2),
  }))

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
  const fillPath = `${d} L ${width.toFixed(2)},${height.toFixed(2)} L 0,${height.toFixed(2)} Z`
  return { linePath: d, fillPath, pts }
}

// ── Logo / Chain icon (self-contained, no imports from ExploreTokens) ─────

function LargeTokenLogo({
  symbol,
  src,
  size = 48,
}: {
  symbol: string
  src: string | null | undefined
  size?: number
}) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          background: `linear-gradient(135deg, ${C.blue}, ${C.purple})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: C.D,
          fontSize: Math.round(size * 0.42),
          fontWeight: 700,
          color: '#fff',
          flexShrink: 0,
        }}
      >
        {symbol.slice(0, 1).toUpperCase()}
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={symbol}
      width={size}
      height={size}
      onError={() => setFailed(true)}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        flexShrink: 0,
        display: 'block',
        objectFit: 'cover',
        background: 'rgba(10,10,10,0.04)',
      }}
    />
  )
}

function SmallChainIcon({ chainId, size = 18 }: { chainId: number; size?: number }) {
  const [failed, setFailed] = useState(false)
  const info = (SUPPORTED_CHAINS as Record<number, { name: string }>)[chainId]
  if (!info) return null
  const src = CHAIN_ICONS[chainId]
  if (!src || failed) {
    const letter = info.name.slice(0, 1).toUpperCase()
    const bg = CHAIN_COLORS[chainId % CHAIN_COLORS.length]
    return (
      <div
        title={info.name}
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          background: bg,
          border: '1px solid rgba(0,0,0,0.2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: C.D,
          fontSize: Math.round(size * 0.55),
          fontWeight: 700,
          color: '#fff',
          flexShrink: 0,
        }}
      >
        {letter}
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={info.name}
      title={info.name}
      width={size}
      height={size}
      onError={() => setFailed(true)}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        border: '1px solid rgba(0,0,0,0.2)',
        flexShrink: 0,
        display: 'block',
        objectFit: 'cover',
        background: 'rgba(10,10,10,0.04)',
      }}
    />
  )
}

// ── Large interactive chart ────────────────────────────────────────────────

function LargeChart({
  data,
  width,
  height,
  isUp,
  hoverIdx,
  setHoverIdx,
}: {
  data: number[]
  width: number
  height: number
  isUp: boolean
  hoverIdx: number | null
  setHoverIdx: (i: number | null) => void
}) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const { linePath, fillPath, pts } = useMemo(
    () => buildSmoothPath(data, width, height),
    [data, width, height],
  )
  const color = isUp ? C.green : C.red
  const gid = `largeSpark-${isUp ? 'up' : 'dn'}`

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left
    // Translate pixel x → SVG viewBox x (since SVG is width-scaled by 100%).
    const svgX = (x / rect.width) * width
    const i = Math.round((svgX / width) * (data.length - 1))
    const clamped = Math.max(0, Math.min(data.length - 1, i))
    setHoverIdx(clamped)
  }

  const hp = hoverIdx != null ? pts[hoverIdx] : null

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: 'block', width: '100%', height, cursor: 'crosshair' }}
      onMouseMove={onMove}
      onMouseLeave={() => setHoverIdx(null)}
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.22} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={fillPath} fill={`url(#${gid})`} />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {hp && (
        <>
          <line
            x1={hp.x}
            x2={hp.x}
            y1={0}
            y2={height}
            stroke="rgba(10,10,10,0.25)"
            strokeWidth={1}
            strokeDasharray="4 4"
          />
          <circle cx={hp.x} cy={hp.y} r={5} fill={color} stroke="#fff" strokeWidth={1.5} />
        </>
      )}
    </svg>
  )
}

// ── Time pills (only 1W functional) ────────────────────────────────────────

const TIME_PILLS = ['1H', '1D', '1W', '1M', '1Y'] as const
const ACTIVE_PILL = '1W'

function TimePills() {
  return (
    <div
      style={{
        display: 'flex',
        gap: 4,
        marginTop: 16,
        padding: 4,
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        width: 'fit-content',
      }}
    >
      {TIME_PILLS.map(p => {
        const active = p === ACTIVE_PILL
        return (
          <button
            key={p}
            type="button"
            title={active ? undefined : 'Coming soon'}
            disabled={!active}
            style={{
              padding: '6px 14px',
              background: active
                ? 'linear-gradient(135deg, rgba(200,81,44,0.22), rgba(200,81,44,0.22))'
                : 'transparent',
              border: active ? '1px solid rgba(200,81,44,0.35)' : '1px solid transparent',
              borderRadius: 7,
              color: active ? C.text : C.dim,
              cursor: active ? 'default' : 'not-allowed',
              opacity: active ? 1 : 0.5,
              fontFamily: C.D,
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: '0.04em',
              transition: 'color 150ms ease',
            }}
          >
            {p}
          </button>
        )
      })}
    </div>
  )
}

// ── Address row ────────────────────────────────────────────────────────────

function AddressRow({
  chainId,
  isNative,
  address,
}: {
  chainId: number
  isNative: boolean
  address: string | null
}) {
  const [copied, setCopied] = useState(false)
  const info = (SUPPORTED_CHAINS as Record<number, { name: string; explorerUrl: string }>)[chainId]
  if (!info) return null

  const explorer = address
    ? `${info.explorerUrl}/${isNative ? 'address' : 'token'}/${address}`
    : null

  const copy = async () => {
    if (!address) return
    try {
      await navigator.clipboard.writeText(address)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {}
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '12px 14px',
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <SmallChainIcon chainId={chainId} size={20} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: C.D, fontSize: 13, color: C.text, fontWeight: 500 }}>
          {info.name}
        </div>
      </div>
      <div
        style={{
          fontFamily: C.M,
          fontSize: 12,
          color: address ? C.sub : C.dim,
          whiteSpace: 'nowrap',
        }}
      >
        {isNative || !address ? 'Native token' : truncateAddr(address)}
      </div>
      {address && !isNative && (
        <>
          <button
            type="button"
            onClick={copy}
            title={copied ? 'Copied!' : 'Copy address'}
            style={{
              padding: '4px 8px',
              background: copied ? 'rgba(0,214,143,0.12)' : 'transparent',
              border: `1px solid ${copied ? 'rgba(0,214,143,0.4)' : C.border}`,
              borderRadius: 6,
              color: copied ? C.green : C.sub,
              cursor: 'pointer',
              fontFamily: C.D,
              fontSize: 11,
              fontWeight: 600,
              transition: 'background 150ms ease, color 150ms ease, border-color 150ms ease',
            }}
          >
            {copied ? '✓' : '⧉'}
          </button>
          {explorer && (
            <a
              href={explorer}
              target="_blank"
              rel="noopener noreferrer"
              title="Open in block explorer"
              style={{
                padding: '4px 8px',
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                color: C.sub,
                fontFamily: C.D,
                fontSize: 11,
                fontWeight: 600,
                textDecoration: 'none',
                transition: 'color 150ms ease, border-color 150ms ease',
              }}
            >
              ↗
            </a>
          )}
        </>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────

export default function TokenDetailView({
  coingeckoId,
  market,
  marketLoading,
  onBack,
  isMobile,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  // Find all tokens matching this coingeckoId — can span multiple chains.
  const tokenInstances = useMemo(
    () => TOKEN_LIST.filter(t => t.coingeckoId === coingeckoId),
    [coingeckoId],
  )

  const primary = tokenInstances[0]
  const chainIds = useMemo(() => {
    const set = new Set<number>()
    for (const t of tokenInstances) set.add(t.chainId)
    return Array.from(set)
  }, [tokenInstances])

  const sparkline = market?.sparkline ?? []
  const hasSparkline = sparkline.length >= 2
  const isUp = hasSparkline ? sparkline[sparkline.length - 1] >= sparkline[0] : true

  // Hovered price overrides current price; change recomputed from series.
  const displayPrice =
    hoverIdx != null && sparkline[hoverIdx] != null ? sparkline[hoverIdx] : market?.price ?? null
  const displayChange =
    hoverIdx != null && hasSparkline && sparkline[0] > 0
      ? ((sparkline[hoverIdx] - sparkline[0]) / sparkline[0]) * 100
      : market?.change24h ?? null

  const chColor =
    displayChange == null || Number.isNaN(displayChange)
      ? C.dim
      : displayChange >= 0
      ? C.green
      : C.red

  const chartWidth = 700
  const chartHeight = isMobile ? 220 : 300

  if (!primary) {
    return (
      <section style={{ padding: '40px 16px', maxWidth: 900, margin: '0 auto' }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            background: 'transparent',
            border: 'none',
            color: C.sub,
            fontFamily: C.D,
            fontSize: 13,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          ← Back to tokens
        </button>
        <div style={{ marginTop: 24, color: C.dim, fontFamily: C.D }}>
          Token not found in registry.
        </div>
      </section>
    )
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '0 0 40px' }}>
      {/* Back */}
      <button
        type="button"
        onClick={onBack}
        onMouseEnter={e => {
          e.currentTarget.style.color = C.text
        }}
        onMouseLeave={e => {
          e.currentTarget.style.color = C.sub
        }}
        style={{
          background: 'transparent',
          border: 'none',
          color: C.sub,
          fontFamily: C.D,
          fontSize: 13,
          fontWeight: 500,
          cursor: 'pointer',
          padding: 0,
          marginBottom: 20,
          letterSpacing: '0.02em',
          transition: 'color 150ms ease',
        }}
      >
        ← Back to tokens
      </button>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <LargeTokenLogo symbol={primary.symbol} src={market?.image ?? null} size={48} />
        <div>
          <h2
            style={{
              fontFamily: C.D,
              fontSize: 28,
              fontWeight: 700,
              color: C.text,
              margin: 0,
              lineHeight: 1.1,
              letterSpacing: '-0.01em',
            }}
          >
            {primary.name}
          </h2>
          <div
            style={{
              fontFamily: C.D,
              fontSize: 13,
              color: C.sub,
              marginTop: 4,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            {primary.symbol}
          </div>
        </div>
      </div>

      {/* Price + change */}
      <div style={{ marginBottom: 12 }}>
        <div
          style={{
            fontFamily: C.M,
            fontSize: isMobile ? 28 : 36,
            fontWeight: 700,
            color: C.text,
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
          }}
        >
          {marketLoading && displayPrice == null ? '—' : formatUsd(displayPrice)}
        </div>
        <div
          style={{
            fontFamily: C.M,
            fontSize: 14,
            fontWeight: 600,
            color: chColor,
            marginTop: 6,
            minHeight: 18,
          }}
        >
          {displayChange == null || Number.isNaN(displayChange) ? (
            '—'
          ) : (
            <>
              <span style={{ marginRight: 4 }}>{displayChange >= 0 ? '▲' : '▼'}</span>
              {Math.abs(displayChange).toFixed(2)}%
              <span style={{ color: C.dim, marginLeft: 8, fontWeight: 500 }}>
                {hoverIdx != null ? 'vs. 7d start' : '24h'}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Chart */}
      <div
        style={{
          background: 'rgba(10,10,10,0.04)',
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          padding: 16,
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          marginTop: 16,
        }}
      >
        {hasSparkline ? (
          <LargeChart
            data={sparkline}
            width={chartWidth}
            height={chartHeight}
            isUp={isUp}
            hoverIdx={hoverIdx}
            setHoverIdx={setHoverIdx}
          />
        ) : (
          <div
            style={{
              height: chartHeight,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: C.dim,
              fontFamily: C.D,
              fontSize: 13,
            }}
          >
            {marketLoading ? 'Loading chart…' : 'No chart data available'}
          </div>
        )}
      </div>

      <TimePills />

      {/* Stats */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr 1fr' : '1fr 1fr 1fr',
          gap: 16,
          marginTop: 32,
          padding: 20,
          background: 'rgba(10,10,10,0.03)',
          border: `1px solid ${C.border}`,
          borderRadius: 12,
        }}
      >
        <StatCell label="Market Cap" value={formatCompactUsd(market?.marketCap ?? null)} />
        <StatCell label="Volume 24h" value={formatCompactUsd(market?.volume ?? null)} />
        <StatCell
          label="Available on"
          value={`${chainIds.length} chain${chainIds.length === 1 ? '' : 's'}`}
        />
      </div>

      {/* Chain list */}
      <SectionTitle>Available chains</SectionTitle>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {chainIds.map(id => {
          const info = (SUPPORTED_CHAINS as Record<number, { name: string }>)[id]
          if (!info) return null
          return (
            <div
              key={id}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                background: 'rgba(10,10,10,0.03)',
                border: `1px solid ${C.border}`,
                borderRadius: 999,
              }}
            >
              <SmallChainIcon chainId={id} size={18} />
              <span style={{ fontFamily: C.D, fontSize: 13, color: C.text }}>{info.name}</span>
            </div>
          )
        })}
      </div>

      {/* Addresses */}
      <SectionTitle>Token addresses</SectionTitle>
      <div
        style={{
          background: 'rgba(10,10,10,0.03)',
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        {tokenInstances.map((t, i) => (
          <div
            key={`${t.chainId}-${t.address ?? 'native'}`}
            style={
              i === tokenInstances.length - 1
                ? { borderBottom: 'none' }
                : undefined
            }
          >
            <AddressRow chainId={t.chainId as ChainId} isNative={t.isNative} address={t.address} />
          </div>
        ))}
      </div>
    </div>
  )
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          fontFamily: C.D,
          fontSize: 11,
          color: C.dim,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ fontFamily: C.M, fontSize: 20, fontWeight: 600, color: C.text }}>{value}</div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        fontFamily: C.D,
        fontSize: 12,
        fontWeight: 700,
        color: C.sub,
        textTransform: 'uppercase',
        letterSpacing: '0.12em',
        margin: '36px 0 14px',
      }}
    >
      {children}
    </h3>
  )
}
