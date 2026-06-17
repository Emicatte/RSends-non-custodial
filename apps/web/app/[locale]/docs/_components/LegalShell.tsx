'use client'

import { ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import { useIsMobile } from '@/hooks/useIsMobile'

type Props = {
  eyebrow: string
  title: string
  lastUpdated: string
  breadcrumbLabel: string
  children: ReactNode
}

export default function LegalShell({ eyebrow, title, lastUpdated, breadcrumbLabel, children }: Props) {
  const isMobile = useIsMobile()
  const t = useTranslations('legal.shell')

  return (
    <main
      style={{
        minHeight: '100dvh',
        background: C.bg,
        color: C.text,
        fontFamily: C.D,
      }}
    >
      <div
        style={{
          padding: isMobile ? '60px 24px' : '80px 96px',
          maxWidth: 880,
          margin: '0 auto',
        }}
      >
        <nav style={{ marginBottom: 40, fontSize: 13 }} aria-label="Breadcrumb">
          <ol
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              listStyle: 'none',
              padding: 0,
              margin: 0,
              color: C.sub,
            }}
          >
            <li>
              <Link href="/" style={{ color: 'inherit', textDecoration: 'none' }}>
                {t('breadcrumb.home')}
              </Link>
            </li>
            <li style={{ color: 'rgba(10,10,10,0.25)' }}>/</li>
            <li>
              <Link href="/docs" style={{ color: 'inherit', textDecoration: 'none' }}>
                {t('breadcrumb.docs')}
              </Link>
            </li>
            <li style={{ color: 'rgba(10,10,10,0.25)' }}>/</li>
            <li style={{ color: C.text, fontWeight: 500 }}>{breadcrumbLabel}</li>
          </ol>
        </nav>

        <div
          role="note"
          style={{
            fontStyle: 'italic',
            fontSize: 12,
            color: C.sub,
            padding: '12px 16px',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            marginBottom: 32,
            lineHeight: 1.6,
          }}
        >
          {t('disclaimer')}
        </div>

        <p
          style={{
            fontFamily: C.M,
            fontSize: 11,
            letterSpacing: '0.18em',
            color: C.purple,
            fontWeight: 500,
            margin: '0 0 12px',
            textTransform: 'uppercase',
          }}
        >
          {eyebrow}
        </p>

        <h1
          style={{
            fontFamily: C.D,
            fontSize: 'clamp(28px, 4vw, 52px)',
            fontWeight: 600,
            color: C.text,
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
            margin: '0 0 16px',
          }}
        >
          {title}
        </h1>

        <p
          style={{
            fontFamily: C.M,
            fontSize: 12,
            color: C.sub,
            margin: '0 0 48px',
          }}
        >
          {t('lastUpdatedLabel')} {lastUpdated}
        </p>

        <div className="legal-content">{children}</div>

        <div
          style={{
            marginTop: 64,
            paddingTop: 32,
            borderTop: `1px solid ${C.border}`,
          }}
        >
          <Link
            href="/"
            style={{
              fontFamily: C.D,
              fontSize: 14,
              fontWeight: 500,
              color: C.purple,
              textDecoration: 'none',
            }}
          >
            {t('backToHome')}
          </Link>
        </div>
      </div>

      <style>{`
        .legal-content h2 {
          font-family: ${C.D};
          font-size: 22px;
          font-weight: 600;
          color: ${C.text};
          letter-spacing: -0.01em;
          margin: 40px 0 12px;
        }
        .legal-content h2:first-child {
          margin-top: 0;
        }
        .legal-content h3 {
          font-family: ${C.D};
          font-size: 16px;
          font-weight: 600;
          color: ${C.text};
          margin: 24px 0 8px;
        }
        .legal-content p {
          font-family: ${C.D};
          font-size: 15px;
          color: ${C.sub};
          line-height: 1.7;
          margin: 0 0 16px;
        }
        .legal-content ul, .legal-content ol {
          font-family: ${C.D};
          font-size: 15px;
          color: ${C.sub};
          line-height: 1.7;
          margin: 0 0 16px;
          padding-left: 24px;
        }
        .legal-content li {
          margin-bottom: 6px;
        }
        .legal-content a {
          color: ${C.purple};
          text-decoration: underline;
          text-underline-offset: 2px;
        }
        .legal-content a:hover {
          text-decoration: none;
        }
        .legal-content strong {
          color: ${C.text};
          font-weight: 600;
        }
        .legal-content code {
          font-family: ${C.M};
          font-size: 13px;
          background: rgba(10,10,10,0.05);
          padding: 1px 6px;
          border-radius: 4px;
          color: ${C.text};
        }
      `}</style>
    </main>
  )
}
