import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import LegalShell from '../_components/LegalShell'
import { richElements } from '../_components/legalRichElements'

type PageProps = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.terms.metadata' })
  return { title: t('title'), description: t('description') }
}

export default async function TermsPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.terms' })

  const eligibilityItems = t.raw('sections.eligibility.items') as string[]
  const custodialItems = t.raw('sections.custodial.items') as string[]
  const prohibitedItems = t.raw('sections.prohibited.items') as string[]
  const obligationsItems = t.raw('sections.obligations.items') as string[]
  const contactLines = t.raw('sections.contact.lines') as string[]

  return (
    <LegalShell
      eyebrow={t('eyebrow')}
      title={t('title')}
      lastUpdated={t('lastUpdated')}
      breadcrumbLabel={t('breadcrumbLabel')}
    >
      <p>{t.rich('intro1', richElements)}</p>
      <p>{t.rich('intro2', richElements)}</p>

      <h2>{t('sections.service.heading')}</h2>
      <p>{t.rich('sections.service.body', richElements)}</p>

      <h2>{t('sections.eligibility.heading')}</h2>
      <p>{t('sections.eligibility.intro')}</p>
      <ul>
        {eligibilityItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.eligibility.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.account.heading')}</h2>
      <p>{t.rich('sections.account.body1', richElements)}</p>
      <p>{t.rich('sections.account.body2', richElements)}</p>

      <h2>{t('sections.custodial.heading')}</h2>
      <p>{t.rich('sections.custodial.intro', richElements)}</p>
      <ul>
        {custodialItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.custodial.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.settlement.heading')}</h2>
      <p>{t.rich('sections.settlement.body', richElements)}</p>

      <h2>{t('sections.fees.heading')}</h2>
      <p>{t.rich('sections.fees.body', richElements)}</p>

      <h2>{t('sections.prohibited.heading')}</h2>
      <p>{t('sections.prohibited.intro')}</p>
      <ul>
        {prohibitedItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.prohibited.items.${i}`, richElements)}</li>
        ))}
      </ul>
      <p>{t.rich('sections.prohibited.note', richElements)}</p>

      <h2>{t('sections.obligations.heading')}</h2>
      <ul>
        {obligationsItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.obligations.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.disclaimers.heading')}</h2>
      <p>{t.rich('sections.disclaimers.body', richElements)}</p>

      <h2>{t('sections.liability.heading')}</h2>
      <p>{t.rich('sections.liability.body', richElements)}</p>

      <h2>{t('sections.indemnity.heading')}</h2>
      <p>{t.rich('sections.indemnity.body', richElements)}</p>

      <h2>{t('sections.termination.heading')}</h2>
      <p>{t.rich('sections.termination.body', richElements)}</p>

      <h2>{t('sections.governingLaw.heading')}</h2>
      <p>{t.rich('sections.governingLaw.body', richElements)}</p>

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
