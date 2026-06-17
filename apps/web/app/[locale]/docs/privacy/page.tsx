import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import LegalShell from '../_components/LegalShell'
import { richElements } from '../_components/legalRichElements'

type PageProps = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.privacy.metadata' })
  return { title: t('title'), description: t('description') }
}

export default async function PrivacyPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'legal.privacy' })

  const dataCollectItems = t.raw('sections.dataCollect.items') as string[]
  const legalBasisItems = t.raw('sections.legalBasis.items') as string[]
  const howWeUseItems = t.raw('sections.howWeUse.items') as string[]
  const dataSharingItems = t.raw('sections.dataSharing.items') as string[]
  const rightsItems = t.raw('sections.rights.items') as string[]
  const addressLines = t.raw('sections.controller.addressLines') as string[]
  const contactLines = t.raw('sections.contact.lines') as string[]

  return (
    <LegalShell
      eyebrow={t('eyebrow')}
      title={t('title')}
      lastUpdated={t('lastUpdated')}
      breadcrumbLabel={t('breadcrumbLabel')}
    >
      <p>{t.rich('intro', richElements)}</p>

      <h2>{t('sections.controller.heading')}</h2>
      <p>{t('sections.controller.intro')}</p>
      <p>
        {addressLines.map((_, i) => (
          <span key={i}>
            {t.rich(`sections.controller.addressLines.${i}`, richElements)}
            {i < addressLines.length - 1 && <br />}
          </span>
        ))}
      </p>

      <h2>{t('sections.dataCollect.heading')}</h2>
      <p>{t('sections.dataCollect.intro')}</p>
      <ul>
        {dataCollectItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.dataCollect.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.legalBasis.heading')}</h2>
      <p>{t('sections.legalBasis.intro')}</p>
      <ul>
        {legalBasisItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.legalBasis.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.howWeUse.heading')}</h2>
      <ul>
        {howWeUseItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.howWeUse.items.${i}`, richElements)}</li>
        ))}
      </ul>

      <h2>{t('sections.dataSharing.heading')}</h2>
      <p>{t('sections.dataSharing.intro')}</p>
      <ul>
        {dataSharingItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.dataSharing.items.${i}`, richElements)}</li>
        ))}
      </ul>
      <p>{t.rich('sections.dataSharing.note', richElements)}</p>

      <h2>{t('sections.transfers.heading')}</h2>
      <p>{t.rich('sections.transfers.body', richElements)}</p>

      <h2>{t('sections.retention.heading')}</h2>
      <p>{t.rich('sections.retention.body', richElements)}</p>

      <h2>{t('sections.rights.heading')}</h2>
      <p>{t('sections.rights.intro')}</p>
      <ul>
        {rightsItems.map((_, i) => (
          <li key={i}>{t.rich(`sections.rights.items.${i}`, richElements)}</li>
        ))}
      </ul>
      <p>{t.rich('sections.rights.howTo', richElements)}</p>
      <p>{t.rich('sections.rights.authority', richElements)}</p>

      <h2>{t('sections.security.heading')}</h2>
      <p>{t.rich('sections.security.body', richElements)}</p>

      <h2>{t('sections.cookies.heading')}</h2>
      <p>{t.rich('sections.cookies.body', richElements)}</p>

      <h2>{t('sections.children.heading')}</h2>
      <p>{t.rich('sections.children.body', richElements)}</p>

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
