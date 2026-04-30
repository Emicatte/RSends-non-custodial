'use client'

import { useTranslations } from 'next-intl'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  accent: '#C45A3C',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
  blueLight: 'rgba(76, 130, 251, 0.08)',
  blue: '#3a6bd1',
}

const CHAIN_BADGE: Record<string, { bg: string; text: string }> = {
  Base:   { bg: 'rgba(0, 82, 255, 0.08)',  text: '#0052ff' },
  Tron:   { bg: 'rgba(255, 6, 10, 0.08)',  text: '#cc0510' },
  Solana: { bg: 'rgba(153, 69, 255, 0.08)', text: '#7c2dc7' },
}

type ChainName = keyof typeof CHAIN_BADGE

type BalanceRow = {
  id: number
  token: string
  chain: ChainName
  usd: string
  qty: string
}

const BALANCES: ReadonlyArray<BalanceRow> = [
  { id: 1, token: 'USDC', chain: 'Base',   usd: '$98,400', qty: '98,400.00 USDC' },
  { id: 2, token: 'ETH',  chain: 'Base',   usd: '$42,100', qty: '12.50 ETH' },
  { id: 3, token: 'USDT', chain: 'Tron',   usd: '$24,300', qty: '24,300.00 USDT' },
  { id: 4, token: 'USDC', chain: 'Solana', usd: '$12,650', qty: '12,650.00 USDC' },
  { id: 5, token: 'DAI',  chain: 'Base',   usd: '$5,000',  qty: '5,000.00 DAI' },
]

const ASSET_COUNT = new Set(BALANCES.map((b) => b.token)).size
const CHAIN_COUNT = new Set(BALANCES.map((b) => b.chain)).size

type Metric = {
  key: 'total' | 'settled' | 'pending'
  value: string
  color: string
}

const METRICS: ReadonlyArray<Metric> = [
  { key: 'total',   value: '$182,450', color: COLORS.ink    },
  { key: 'settled', value: '$174,200', color: COLORS.green  },
  { key: 'pending', value: '$8,250',   color: COLORS.orange },
]

export default function BalancesPage() {
  const t = useTranslations('app.balances')

  return (
    <main style={{ padding: '24px 32px 80px', maxWidth: 1200, margin: '0 auto' }}>
      {/* Sample-data banner */}
      <div
        role="note"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 14px',
          marginBottom: 20,
          background: COLORS.blueLight,
          border: `1px solid rgba(76, 130, 251, 0.18)`,
          borderRadius: 8,
          color: COLORS.blue,
          fontFamily: 'var(--font-display)',
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        {t('banner')}
      </div>

      {/* Metric cards */}
      <div
        className="grid grid-cols-1 sm:grid-cols-3 gap-4"
        style={{ marginBottom: 24 }}
      >
        {METRICS.map((m) => (
          <div
            key={m.key}
            style={{
              background: COLORS.paper,
              border: `1px solid ${COLORS.border}`,
              borderRadius: 12,
              padding: '16px 18px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 11,
                fontWeight: 700,
                color: COLORS.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
              }}
            >
              {t(`metrics.${m.key}`)}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 26,
                fontWeight: 700,
                color: m.color,
                letterSpacing: '-0.02em',
                lineHeight: 1.1,
              }}
            >
              {m.value}
            </div>
          </div>
        ))}
      </div>

      {/* Breakdown by token */}
      <section
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: '20px 22px',
        }}
      >
        <header style={{ marginBottom: 14 }}>
          <h2
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 14,
              fontWeight: 700,
              color: COLORS.ink,
              margin: '0 0 4px',
              letterSpacing: '-0.01em',
            }}
          >
            {t('breakdown.title')}
          </h2>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              fontWeight: 500,
              color: COLORS.muted,
            }}
          >
            {t('breakdown.subtitle', { assets: ASSET_COUNT, chains: CHAIN_COUNT })}
          </div>
        </header>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {BALANCES.map((row) => {
            const chainBadge = CHAIN_BADGE[row.chain]
            return (
              <div
                key={row.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: COLORS.paper,
                  borderRadius: 8,
                  padding: '10px 14px',
                  gap: 12,
                }}
              >
                {/* Left: token + chain */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                  <div
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 14,
                      fontWeight: 700,
                      color: COLORS.ink,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {row.token}
                  </div>
                  <span
                    style={{
                      display: 'inline-block',
                      alignSelf: 'flex-start',
                      padding: '2px 7px',
                      borderRadius: 6,
                      background: chainBadge.bg,
                      color: chainBadge.text,
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: '0.02em',
                      fontFamily: 'var(--font-display)',
                    }}
                  >
                    {row.chain}
                  </span>
                </div>

                {/* Right: USD amount + token quantity */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                  <div
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 16,
                      fontWeight: 700,
                      color: COLORS.ink,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {row.usd}
                  </div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
                      fontSize: 11,
                      fontWeight: 500,
                      color: COLORS.muted,
                    }}
                  >
                    {row.qty}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </main>
  )
}
