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
const NAMESPACES = ['vision', 'team', 'onboarding', 'pricing', 'howItWorks'] as const

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

/**
 * The per-transaction fee model was retired (2026-07-15): RSends is a flat
 * monthly subscription agreed per merchant at onboarding, with no public
 * price figure. No marketing namespace may reintroduce a price number or
 * the old flat-fee claim. (settings/legal/docs are separate surfaces with
 * their own rules — this guards the marketing copy only.)
 */
describe('retired fee model stays out of marketing copy', () => {
  const MARKETING_NAMESPACES = ['pricing', 'howItWorks', 'hero', 'twoPaths'] as const
  // Price figures and the retired flat-fee slogan. A NEGATION of the fee
  // ("Is there a per-transaction fee? No.") is exactly the copy we want, so
  // the fee wording itself is not banned — only figures and the old claim.
  const FORBIDDEN = [/€\s?\d/, /\d\s?€/, /0[.,]60/, /never a percentage/i, /mai una %/i, /flat fee/i]

  it.each(Object.keys(LOCALES))('%s carries no price figures or flat-fee claims', locale => {
    for (const namespace of MARKETING_NAMESPACES) {
      for (const s of leafStrings(LOCALES[locale][namespace])) {
        for (const pattern of FORBIDDEN) {
          expect({ locale, namespace, value: s, matches: pattern.test(s) }).toEqual({
            locale,
            namespace,
            value: s,
            matches: false,
          })
        }
      }
    }
  })
})
