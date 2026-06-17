import { defineRouting } from 'next-intl/routing'

export const routing = defineRouting({
  locales: ['en', 'it', 'es', 'fr', 'de'],
  defaultLocale: 'en',
  localePrefix: 'always',
})

export type Locale = (typeof routing.locales)[number]
