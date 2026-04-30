'use client'

import { useTranslations } from 'next-intl'

export default function ReportsPage() {
  const t = useTranslations('app.sidebar')
  return (
    <main style={{ padding: '32px 32px', maxWidth: 1200, margin: '0 auto' }}>
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 28,
          fontWeight: 700,
          color: '#1a1a1a',
          letterSpacing: '-0.02em',
        }}
      >
        {t('reports')}
      </h1>
    </main>
  )
}
