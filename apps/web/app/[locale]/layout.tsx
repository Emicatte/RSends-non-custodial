import { NextIntlClientProvider } from 'next-intl'
import { getMessages } from 'next-intl/server'
import { notFound } from 'next/navigation'
import { routing, type Locale } from '@/i18n/routing'
import FooterMount from '@/components/FooterMount'
import HeaderMount from '@/components/marketing/HeaderMount'
import { OAuthConflictListener } from '@/components/auth/OAuthConflictListener'

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params

  if (!routing.locales.includes(locale as Locale)) {
    notFound()
  }

  const messages = await getMessages()

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <HeaderMount />
      {children}
      <FooterMount />
      {/* OAuth email-collision (409) → AccountLinkingModal; needs the i18n
          context, so it lives here rather than next to AuthBootstrap. */}
      <OAuthConflictListener />
    </NextIntlClientProvider>
  )
}
