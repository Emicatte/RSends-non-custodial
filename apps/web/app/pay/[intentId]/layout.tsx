import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { NextIntlClientProvider } from 'next-intl'
import { negotiateLocale } from '@/i18n/acceptLanguage'
import { routing } from '@/i18n/routing'

/**
 * Server layout for the hosted checkout.
 *
 * /pay lives outside the locale-prefixed tree (no /{locale}/ segment,
 * excluded from the next-intl middleware), so the locale is negotiated here
 * from Accept-Language against the supported set (default en) and the
 * NextIntlClientProvider is mounted manually with ONLY the payer-facing
 * `pay` namespace — merchant/dashboard strings never ship to payers.
 *
 * Metadata is deliberately generic: no merchant name, no amounts, nothing
 * payment-specific may leak into link previews.
 */

export const metadata: Metadata = {
  title: 'RSends checkout',
  description: 'Complete your payment on RSends.',
  robots: { index: false, follow: false },
}

export default async function PayIntentLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const acceptLanguage = headers().get('accept-language')
  const locale = negotiateLocale(
    acceptLanguage,
    routing.locales,
    routing.defaultLocale,
  )
  const messages = (await import(`@/messages/${locale}.json`)).default as {
    pay: Record<string, unknown>
  }

  return (
    <NextIntlClientProvider
      locale={locale}
      messages={{ pay: messages.pay }}
      timeZone="UTC"
    >
      {children}
    </NextIntlClientProvider>
  )
}
