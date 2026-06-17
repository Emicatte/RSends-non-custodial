import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import { getTranslations } from 'next-intl/server'
import { authOptions } from '@/lib/auth-options'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { OrgSwitcher } from '@/components/settings/OrgSwitcher'
import AuthHeader from '@/components/auth/AuthHeader'

export default async function SettingsLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  const session = await getServerSession(authOptions)
  if (!session) {
    redirect(`/${locale}`)
  }
  const t = await getTranslations({ locale, namespace: 'settings' })

  return (
    <div style={{ minHeight: '100vh', background: '#FAFAFA' }}>
      <AuthHeader />
      <div className="max-w-5xl mx-auto px-6 py-10" style={{ paddingTop: '5rem' }}>
        <header className="mb-8 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold" style={{ color: '#2C2C2A' }}>
              {t('title')}
            </h1>
            <p className="text-sm mt-2" style={{ color: '#888780' }}>
              {t('subtitle')}
            </p>
          </div>
          <OrgSwitcher />
        </header>
        <div className="flex flex-col md:flex-row gap-8">
          <SettingsSidebar locale={locale} />
          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </div>
    </div>
  )
}
