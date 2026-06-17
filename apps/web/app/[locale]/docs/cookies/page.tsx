import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import LegalShell from '../_components/LegalShell'
import { richElements } from '../_components/legalRichElements'

type PageProps = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.cookies.metadata' })
  return { title: t('title'), description: t('description') }
}

export default async function CookiesPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.cookies' })

  const necessaryItems = t.raw('sections.categories.necessary.items') as string[]
  const functionalItems = t.raw('sections.categories.functional.items') as string[]
  const browsers = t.raw('sections.managing.browsers') as string[]

  return (
    <LegalShell
      eyebrow={t('eyebrow')}
      title={t('title')}
      lastUpdated={t('lastUpdated')}
      breadcrumbLabel={t('breadcrumbLabel')}
    >
      <p>{t.rich('intro', richElements)}</p>

      <h2>{t('sections.what.heading')}</h2>
      <p>{t.rich('sections.what.body', richElements)}</p>

      <h2>{t('sections.categories.heading')}</h2>

      <h3>{t('sections.categories.necessary.heading')}</h3>
      <p>{t.rich('sections.categories.necessary.body', richElements)}</p>
      <ul>
        {necessaryItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.categories.necessary.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h3>{t('sections.categories.functional.heading')}</h3>
      <p>{t.rich('sections.categories.functional.body', richElements)}</p>
      <ul>
        {functionalItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.categories.functional.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h3>{t('sections.categories.analytics.heading')}</h3>
      <p>{t.rich('sections.categories.analytics.body', richElements)}</p>

      <h3>{t('sections.categories.advertising.heading')}</h3>
      <p>{t.rich('sections.categories.advertising.body', richElements)}</p>

      <h2>{t('sections.managing.heading')}</h2>
      <p>{t.rich('sections.managing.body', richElements)}</p>
      <p>{t('sections.managing.browsersIntro')}</p>
      <ul>
        {browsers.map((_, i) => (
          <li key={i}>{t.rich(`sections.managing.browsers.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.changes.heading')}</h2>
      <p>{t.rich('sections.changes.body', richElements)}</p>

      <h2>{t('sections.contact.heading')}</h2>
      <p>{t.rich('sections.contact.body', richElements)}</p>
    </LegalShell>
  )
}
