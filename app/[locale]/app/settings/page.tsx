'use client'

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
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.08)',
}

type FieldKey =
  | 'apiKey'
  | 'webhookUrl'
  | 'rateLimit'
  | 'companyName'
  | 'contactEmail'
  | 'kybStatus'
  | 'authMethod'
  | 'twoFa'
  | 'ipWhitelist'
  | 'failedTxAlerts'
  | 'dailyDigest'
  | 'thresholdAlerts'

type ValueRender =
  | { kind: 'text'; value: string }
  | { kind: 'mono'; value: string }
  | { kind: 'badge'; tone: 'green' | 'red'; valueKey: 'verified' | 'enabled' | 'disabled' }
  | { kind: 'translatedCount'; valueKey: 'addresses'; count: number }

type Row = { field: FieldKey; render: ValueRender }

type Box = {
  key: 'api' | 'merchant' | 'security' | 'notifications'
  rows: ReadonlyArray<Row>
}

const BOXES: ReadonlyArray<Box> = [
  {
    key: 'api',
    rows: [
      { field: 'apiKey',     render: { kind: 'mono',  value: 'rs_live_••••••••a3f2' } },
      { field: 'webhookUrl', render: { kind: 'mono',  value: 'https://api.acme.com/webhooks/rsends' } },
      { field: 'rateLimit',  render: { kind: 'text',  value: '1,000 req/min' } },
    ],
  },
  {
    key: 'merchant',
    rows: [
      { field: 'companyName',  render: { kind: 'text',  value: 'RPagos SRL' } },
      { field: 'contactEmail', render: { kind: 'text',  value: 'ops@rpagos.io' } },
      { field: 'kybStatus',    render: { kind: 'badge', tone: 'green', valueKey: 'verified' } },
    ],
  },
  {
    key: 'security',
    rows: [
      { field: 'authMethod',  render: { kind: 'text',  value: 'SIWE + JWT' } },
      { field: 'twoFa',       render: { kind: 'badge', tone: 'green', valueKey: 'enabled' } },
      { field: 'ipWhitelist', render: { kind: 'translatedCount', valueKey: 'addresses', count: 3 } },
    ],
  },
  {
    key: 'notifications',
    rows: [
      { field: 'failedTxAlerts',  render: { kind: 'badge', tone: 'green', valueKey: 'enabled' } },
      { field: 'dailyDigest',     render: { kind: 'text',  value: '08:00 CET' } },
      { field: 'thresholdAlerts', render: { kind: 'text',  value: '$10,000' } },
    ],
  },
]

export default function SettingsPage() {
  const t = useTranslations('app.settings')

  return (
    <main className="rp-app-page">
      {/* 2x2 grid (1 col on mobile, 2 on md+) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {BOXES.map((box) => (
          <section
            key={box.key}
            style={{
              background: COLORS.paper,
              border: `1px solid ${COLORS.border}`,
              borderRadius: 8,
              padding: '14px 16px',
            }}
          >
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 13,
                fontWeight: 700,
                color: COLORS.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                margin: '0 0 12px',
              }}
            >
              {t(`boxes.${box.key}`)}
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {box.rows.map((row) => (
                <div
                  key={row.field}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    minWidth: 0,
                  }}
                >
                  <span
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: COLORS.muted,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t(`fields.${row.field}`)}
                  </span>
                  <SettingValue render={row.render} t={t} />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}

function SettingValue({
  render,
  t,
}: {
  render: ValueRender
  t: ReturnType<typeof useTranslations>
}) {
  if (render.kind === 'badge') {
    const palette =
      render.tone === 'green'
        ? { bg: COLORS.greenLight, text: COLORS.green }
        : { bg: COLORS.redLight, text: COLORS.red }
    return (
      <span
        style={{
          display: 'inline-block',
          padding: '3px 8px',
          borderRadius: 6,
          background: palette.bg,
          color: palette.text,
          fontSize: 11,
          fontWeight: 700,
          fontFamily: 'var(--font-display)',
        }}
      >
        {t(`values.${render.valueKey}`)}
      </span>
    )
  }

  if (render.kind === 'translatedCount') {
    return (
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 13,
          fontWeight: 700,
          color: COLORS.ink,
          textAlign: 'right',
        }}
      >
        {t(`values.${render.valueKey}`, { count: render.count })}
      </span>
    )
  }

  return (
    <span
      style={{
        fontFamily:
          render.kind === 'mono'
            ? 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)'
            : 'var(--font-display)',
        fontSize: 13,
        fontWeight: 700,
        color: COLORS.ink,
        textAlign: 'right',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        maxWidth: '60%',
      }}
      title={render.value}
    >
      {render.value}
    </span>
  )
}
