'use client'

import { useTranslations } from 'next-intl'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
}

type ClientStatus = 'active' | 'onboarding'

const STATUS_BADGE: Record<ClientStatus, { bg: string; text: string }> = {
  active:     { bg: COLORS.greenLight,  text: COLORS.green  },
  onboarding: { bg: COLORS.orangeLight, text: COLORS.orange },
}

type Client = {
  id: number
  name: string
  chain: string
  txCount: number
  volume: string
  status: ClientStatus
}

const CLIENTS: ReadonlyArray<Client> = [
  { id: 1, name: 'Acme Corp',     chain: 'Base',   txCount: 247, volume: '$48,200', status: 'active' },
  { id: 2, name: 'MediPay EU',    chain: 'Tron',   txCount: 132, volume: '$24,500', status: 'active' },
  { id: 3, name: 'TechFlow Ltd',  chain: 'Base',   txCount: 89,  volume: '$18,900', status: 'active' },
  { id: 4, name: 'NovaPay',       chain: 'Solana', txCount: 12,  volume: '$3,400',  status: 'onboarding' },
]

const ACTIVE_COUNT = 14

export default function ClientsPage() {
  const t = useTranslations('app.clients')

  return (
    <main style={{ padding: '24px 32px 80px', maxWidth: 1200, margin: '0 auto' }}>
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 28,
          fontWeight: 700,
          color: COLORS.ink,
          letterSpacing: '-0.02em',
          margin: '0 0 20px',
        }}
      >
        {t('title')}
      </h1>

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
            {t('card.title')}
          </h2>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              fontWeight: 500,
              color: COLORS.muted,
            }}
          >
            {t('card.subtitle', { count: ACTIVE_COUNT })}
          </div>
        </header>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {CLIENTS.map((c) => {
            const statusBadge = STATUS_BADGE[c.status]
            return (
              <div
                key={c.id}
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
                {/* Left: name + chain · tx count */}
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
                    {c.name}
                  </div>
                  <div
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: COLORS.muted,
                    }}
                  >
                    {t('rowSubtitle', { chain: c.chain, count: c.txCount })}
                  </div>
                </div>

                {/* Right: volume + status badge */}
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
                    {c.volume}
                  </div>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '3px 8px',
                      borderRadius: 6,
                      background: statusBadge.bg,
                      color: statusBadge.text,
                      fontSize: 11,
                      fontWeight: 700,
                      fontFamily: 'var(--font-display)',
                    }}
                  >
                    {t(`status.${c.status}`)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </main>
  )
}
