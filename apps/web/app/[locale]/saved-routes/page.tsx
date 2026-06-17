import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { FeaturePage } from '@/components/features/FeaturePage'

type PageProps = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'features.savedRoutes.metadata' })
  return { title: t('title'), description: t('description') }
}

export default function SavedRoutesPage() {
  return <FeaturePage featureKey="savedRoutes" />
}
