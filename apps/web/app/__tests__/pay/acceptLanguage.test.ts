/**
 * i18n/acceptLanguage — pure Accept-Language negotiation for /pay, which
 * lives outside the locale-prefixed tree (no /en/ segment, middleware
 * excluded). Payers get their browser language when supported, else English.
 */
import { negotiateLocale } from '@/i18n/acceptLanguage'

const LOCALES = ['en', 'it', 'es', 'fr', 'de'] as const

describe('negotiateLocale', () => {
  it('picks the highest-q supported language', () => {
    expect(negotiateLocale('it-IT,it;q=0.9,en;q=0.8', LOCALES, 'en')).toBe('it')
    expect(negotiateLocale('en-US,en;q=0.9', LOCALES, 'en')).toBe('en')
  })

  it('reduces region subtags to the base language', () => {
    expect(negotiateLocale('fr-CA', LOCALES, 'en')).toBe('fr')
    expect(negotiateLocale('de-AT,de;q=0.7', LOCALES, 'en')).toBe('de')
  })

  it('skips unsupported languages and honors q ordering', () => {
    expect(negotiateLocale('ja,es;q=0.6', LOCALES, 'en')).toBe('es')
    expect(negotiateLocale('ja;q=0.9,pt;q=0.8', LOCALES, 'en')).toBe('en')
  })

  it('q-values reorder preferences', () => {
    expect(negotiateLocale('en;q=0.5,it;q=0.9', LOCALES, 'en')).toBe('it')
  })

  it('wildcard, empty, null and garbage fall back to the default', () => {
    expect(negotiateLocale('*', LOCALES, 'en')).toBe('en')
    expect(negotiateLocale('', LOCALES, 'en')).toBe('en')
    expect(negotiateLocale(null, LOCALES, 'en')).toBe('en')
    expect(negotiateLocale(';;;===,,,', LOCALES, 'en')).toBe('en')
  })

  it('malformed q parameters are ignored, not fatal', () => {
    expect(negotiateLocale('it;q=abc,es;q=0.5', LOCALES, 'en')).toBe('it')
  })
})
