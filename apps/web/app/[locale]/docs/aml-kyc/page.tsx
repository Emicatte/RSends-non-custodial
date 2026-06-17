import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import LegalShell from '../_components/LegalShell'
import { richElements } from '../_components/legalRichElements'

type PageProps = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.amlKyc.metadata' })
  return { title: t('title'), description: t('description') }
}

export default async function AmlKycPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.amlKyc' })

  const frameworkItems = t.raw('sections.framework.items') as string[]
  const threeLevelItems = t.raw('sections.threeLevel.items') as string[]
  const cddItems = t.raw('sections.cdd.items') as string[]
  const cooperationItems = t.raw('sections.cooperation.items') as string[]
  const contactLines = t.raw('sections.contact.lines') as string[]

  return (
    <LegalShell
      eyebrow={t('eyebrow')}
      title={t('title')}
      lastUpdated={t('lastUpdated')}
      breadcrumbLabel={t('breadcrumbLabel')}
    >
      <p>{t.rich('intro', richElements)}</p>

      <h2>{t('sections.framework.heading')}</h2>
      <p>{t('sections.framework.intro')}</p>
      <ul>
        {frameworkItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.framework.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.threeLevel.heading')}</h2>
      <p>{t('sections.threeLevel.intro')}</p>
      <ol>
        {threeLevelItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.threeLevel.items.${i}`, richElements)}</li>
        ))}
      </ol>

      <h2>{t('sections.cdd.heading')}</h2>
      <p>{t('sections.cdd.intro')}</p>
      <ul>
        {cddItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.cdd.items.${i}`, richElements)}</li>
        ))}
      </ul>
      <p>{t.rich('sections.cdd.note', richElements)}</p>

      <h2>{t('sections.sourceOfFunds.heading')}</h2>
      <p>{t.rich('sections.sourceOfFunds.body', richElements)}</p>

      <h2>{t('sections.sanctions.heading')}</h2>
      <p>{t.rich('sections.sanctions.body1', richElements)}</p>
      <p>{t.rich('sections.sanctions.body2', richElements)}</p>

      <h2>{t('sections.sar.heading')}</h2>
      <p>{t.rich('sections.sar.body', richElements)}</p>

      <h2>{t('sections.records.heading')}</h2>
      <p>{t.rich('sections.records.body', richElements)}</p>

      <h2>{t('sections.cooperation.heading')}</h2>
      <p>{t('sections.cooperation.intro')}</p>
      <ul>
        {cooperationItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.cooperation.items.${i}`, richElements)}</li>
        ))}
      </ul>
      <p>{t.rich('sections.cooperation.note', richElements)}</p>

      <h2>{t('sections.riskBased.heading')}</h2>
      <p>{t.rich('sections.riskBased.body', richElements)}</p>

      <h2>{t('sections.changes.heading')}</h2>
      <p>{t.rich('sections.changes.body', richElements)}</p>

      <h2>{t('sections.contact.heading')}</h2>
      <p>
        {contactLines.map((_, i) => (
          <span key={i}>
            {t.rich(`sections.contact.lines.${i}`, richElements)}
            {i < contactLines.length - 1 && <br />}
          </span>
        ))}
      </p>
    </LegalShell>
  )
}
