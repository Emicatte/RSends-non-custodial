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
}

type MetricKey = 'volumeApr' | 'feesCollected' | 'avgTxSize'

const METRICS: ReadonlyArray<{ key: MetricKey; value: string }> = [
  { key: 'volumeApr',     value: '$892,400' },
  { key: 'feesCollected', value: '$4,462' },
  { key: 'avgTxSize',     value: '$1,420' },
]

type ExportKey = 'dac8' | 'taxIt' | 'customPeriod'

const EXPORTS: ReadonlyArray<ExportKey> = ['dac8', 'taxIt', 'customPeriod']

const exportBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 13,
  fontWeight: 600,
  color: COLORS.ink,
  background: COLORS.white,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 8,
  padding: '10px 16px',
  cursor: 'pointer',
  textAlign: 'center',
  transition: 'background 0.15s',
}

export default function ReportsPage() {
  const t = useTranslations('app.reports')

  const handleExportClick = () => {
    // UI only — backend integration deferred
    if (typeof window !== 'undefined') {
      window.alert(t('export.comingSoon'))
    }
  }

  return (
    <main style={{ padding: '24px 32px 80px', maxWidth: 1200, margin: '0 auto' }}>
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
                color: COLORS.ink,
                letterSpacing: '-0.02em',
                lineHeight: 1.1,
              }}
            >
              {m.value}
            </div>
          </div>
        ))}
      </div>

      {/* Monthly volume chart */}
      <section
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: '20px 22px',
          marginBottom: 24,
        }}
      >
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            fontWeight: 700,
            color: COLORS.ink,
            margin: '0 0 16px',
            letterSpacing: '-0.01em',
          }}
        >
          {t('monthlyVolume.title')}
        </h2>
        <div
          style={{
            border: `1px dashed ${COLORS.border}`,
            borderRadius: 8,
            height: 280,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: COLORS.subtle,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {t('monthlyVolume.comingSoon')}
        </div>
      </section>

      {/* Export buttons */}
      <div
        className="grid grid-cols-1 sm:grid-cols-3 gap-3"
      >
        {EXPORTS.map((key) => (
          <button
            key={key}
            type="button"
            onClick={handleExportClick}
            style={exportBtnStyle}
          >
            {t(`export.${key}`)}
          </button>
        ))}
      </div>
    </main>
  )
}
