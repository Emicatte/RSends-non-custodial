'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  accent: '#C45A3C',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
}

type TabKey = 'forwarding' | 'splits' | 'sweeper'
type CardStatus = 'active' | 'paused'

const TABS: ReadonlyArray<TabKey> = ['forwarding', 'splits', 'sweeper']

const STATUS_BADGE: Record<CardStatus, { bg: string; text: string }> = {
  active: { bg: COLORS.greenLight,  text: COLORS.green  },
  paused: { bg: COLORS.orangeLight, text: COLORS.orange },
}

type RuleCard = {
  id: number
  name: string
  description: string
  status: CardStatus
}

const FORWARDING: ReadonlyArray<RuleCard> = [
  { id: 1, name: 'Auto-forward USDC',  description: 'Forwards all USDC payments to treasury wallet',     status: 'active' },
  { id: 2, name: 'Tron sweep daily',   description: 'Sweeps Tron balance to cold storage at 02:00 UTC', status: 'active' },
  { id: 3, name: 'ETH > 0.5 forward',  description: 'Auto-forwards ETH balance when above 0.5',         status: 'paused' },
]

const SPLITS: ReadonlyArray<RuleCard> = [
  { id: 1, name: 'Revenue split — Acme 70/20/10', description: 'Acme Corp main / fees / reserve',     status: 'active' },
  { id: 2, name: 'Fee split — MediPay 90/10',     description: 'MediPay EU operating / platform fee', status: 'active' },
]

const SWEEPER: ReadonlyArray<RuleCard> = [
  { id: 1, name: 'Nightly sweep — Base', description: 'Base chain → cold wallet · 02:00 UTC',         status: 'active' },
  { id: 2, name: 'Weekly sweep — Tron',  description: 'Tron chain → treasury · Sundays 03:00 UTC',    status: 'active' },
]

const TAB_DATA: Record<TabKey, ReadonlyArray<RuleCard>> = {
  forwarding: FORWARDING,
  splits:     SPLITS,
  sweeper:    SWEEPER,
}

const newButtonStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 12,
  fontWeight: 600,
  color: COLORS.white,
  background: COLORS.accent,
  border: 'none',
  borderRadius: 8,
  padding: '8px 14px',
  height: 36,
  cursor: 'pointer',
}

export default function CommandCenterPage() {
  const t = useTranslations('app.commandCenter')
  const [activeTab, setActiveTab] = useState<TabKey>('forwarding')

  const cards = TAB_DATA[activeTab]
  const newButtonLabel =
    activeTab === 'forwarding' || activeTab === 'sweeper'
      ? t('actions.newRule')
      : t('actions.newSplit')
  const showNewButton = activeTab !== 'sweeper'

  return (
    <main style={{ padding: '24px 32px 80px', maxWidth: 1200, margin: '0 auto' }}>
      {/* Tabs */}
      <div
        role="tablist"
        aria-label={t('title')}
        style={{
          display: 'flex',
          gap: 4,
          borderBottom: `1px solid ${COLORS.border}`,
          marginBottom: 20,
        }}
      >
        {TABS.map((tab) => {
          const active = activeTab === tab
          return (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(tab)}
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 13,
                fontWeight: active ? 700 : 500,
                color: active ? COLORS.accent : COLORS.muted,
                background: 'transparent',
                border: 'none',
                padding: '10px 16px',
                cursor: 'pointer',
                borderBottom: `2px solid ${active ? COLORS.accent : 'transparent'}`,
                marginBottom: -1,
                transition: 'color 0.15s',
              }}
            >
              {t(`tabs.${tab}`)}
            </button>
          )
        })}
      </div>

      {/* Header row: card list title + action button */}
      {showNewButton && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            marginBottom: 12,
          }}
        >
          <button type="button" style={newButtonStyle}>
            {newButtonLabel}
          </button>
        </div>
      )}

      {/* Card list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {cards.map((card) => {
          const statusBadge = STATUS_BADGE[card.status]
          return (
            <div
              key={card.id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: COLORS.paper,
                borderRadius: 8,
                padding: '12px 14px',
                gap: 12,
              }}
            >
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
                  {card.name}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontSize: 12,
                    fontWeight: 500,
                    color: COLORS.muted,
                  }}
                >
                  {card.description}
                </div>
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
                  flexShrink: 0,
                }}
              >
                {t(`status.${card.status}`)}
              </span>
            </div>
          )
        })}
      </div>
    </main>
  )
}
