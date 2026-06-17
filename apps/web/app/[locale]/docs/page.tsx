import type { Metadata } from 'next'
import { Link } from '@/i18n/navigation'
import { ApiDocs } from './_components/ApiDocs'

export const metadata: Metadata = {
  title: 'API Documentation — RSends',
  description:
    'REST API reference and integration guide for the RSends multi-chain B2B crypto payment gateway.',
}

export default function DocsPage() {
  return (
    <main style={{
      minHeight: '100dvh',
      fontFamily: 'var(--font-display)',
      color: '#0A0A0A',
      background: '#FAFAFA',
    }}>
      {/* ── Header (preserved 1:1 from the previous page) ── */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '64px 24px 0' }}>

        <nav style={{ marginBottom: 40, fontSize: 13 }} aria-label="Breadcrumb">
          <ol style={{ display: 'flex', alignItems: 'center', gap: 8, listStyle: 'none', padding: 0, margin: 0, color: 'rgba(10,10,10,0.55)' }}>
            <li>
              <Link href="/" style={{ color: 'inherit', textDecoration: 'none' }}>
                Home
              </Link>
            </li>
            <li style={{ color: 'rgba(10,10,10,0.25)' }}>/</li>
            <li style={{ color: '#0A0A0A', fontWeight: 500 }}>Docs</li>
          </ol>
        </nav>

        <p style={{
          fontSize: 11,
          letterSpacing: '0.18em',
          color: '#C8512C',
          fontWeight: 500,
          marginBottom: 16,
          textTransform: 'uppercase',
        }}>
          API Documentation
        </p>

        <h1 style={{
          fontSize: 'clamp(36px, 6vw, 56px)',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          lineHeight: 1.1,
          margin: '0 0 16px',
        }}>
          Docs
        </h1>

        <p style={{
          fontSize: 16,
          color: 'rgba(10,10,10,0.6)',
          lineHeight: 1.6,
          margin: '0 0 8px',
          maxWidth: 640,
        }}>
          REST reference for the RSends multi-chain B2B crypto payment gateway — transactions,
          distributions, splits, execution and webhooks.
        </p>
      </div>

      {/* ── Interactive docs body (sidebar + content) ── */}
      <ApiDocs />
    </main>
  )
}
