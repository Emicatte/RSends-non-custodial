/**
 * Checked namespaces (marketing /vision + /team, and the onboarding flow
 * incl. the /app Get-started checklist) must be present in every locale
 * file with the same key shape as English (the source of truth) — no
 * missing-key fallbacks in any locale.
 */
import enMessages from '@/messages/en.json'
import itMessages from '@/messages/it.json'
import esMessages from '@/messages/es.json'
import frMessages from '@/messages/fr.json'
import deMessages from '@/messages/de.json'

const LOCALES: Record<string, Record<string, unknown>> = {
  en: enMessages,
  it: itMessages,
  es: esMessages,
  fr: frMessages,
  de: deMessages,
}
const NAMESPACES = ['vision', 'team', 'onboarding'] as const

/** Recursively collect dot-paths of every leaf, tagging arrays with length. */
function keyShape(node: unknown, prefix = ''): string[] {
  if (Array.isArray(node)) {
    return node.flatMap((item, i) => keyShape(item, `${prefix}[${i}]`))
  }
  if (node !== null && typeof node === 'object') {
    return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
      keyShape(v, prefix ? `${prefix}.${k}` : k),
    )
  }
  return [prefix]
}

/** Recursively collect every leaf string value. */
function leafStrings(node: unknown): string[] {
  if (Array.isArray(node)) return node.flatMap(leafStrings)
  if (node !== null && typeof node === 'object') {
    return Object.values(node as Record<string, unknown>).flatMap(leafStrings)
  }
  return typeof node === 'string' ? [node] : []
}

describe.each(NAMESPACES)('"%s" namespace', namespace => {
  it('exists in every locale', () => {
    for (const [locale, messages] of Object.entries(LOCALES)) {
      expect(messages[namespace]).toBeDefined()
    }
  })

  it.each(Object.keys(LOCALES).filter(l => l !== 'en'))(
    '%s has the exact same key shape as en',
    locale => {
      const expected = keyShape(LOCALES.en[namespace]).sort()
      const actual = keyShape(LOCALES[locale][namespace]).sort()
      expect(actual).toEqual(expected)
    },
  )

  it.each(Object.keys(LOCALES))('%s has no empty strings', locale => {
    for (const s of leafStrings(LOCALES[locale][namespace])) {
      expect(s.trim()).not.toBe('')
    }
  })
})
