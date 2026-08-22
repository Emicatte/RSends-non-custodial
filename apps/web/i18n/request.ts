import { getRequestConfig } from 'next-intl/server'
import { routing } from './routing'

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale

  if (!locale || !routing.locales.includes(locale as any)) {
    locale = routing.defaultLocale
  }

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
    // Without an explicit zone, next-intl's formatters resolve to the server's
    // timezone during SSR and the visitor's in the browser — the same value
    // renders as two different strings and React tears down the root. Pinned to
    // UTC, matching app/pay/[intentId]/layout.tsx. Latent today (no
    // useFormatter call sites yet); this keeps the first one from reintroducing
    // the bug.
    timeZone: 'UTC',
  }
})
