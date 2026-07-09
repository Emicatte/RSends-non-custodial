/**
 * Pure Accept-Language negotiation for routes outside the locale-prefixed
 * tree (the /pay hosted checkout has no /{locale}/ segment and is excluded
 * from the next-intl middleware). RFC 9110 semantics, reduced to what the
 * header actually needs: split on commas, honor q-values (default 1),
 * reduce region subtags (fr-CA -> fr), first supported wins.
 */

export function negotiateLocale(
  header: string | null,
  locales: readonly string[],
  defaultLocale: string,
): string {
  if (!header) return defaultLocale

  const candidates: Array<{ lang: string; q: number; index: number }> = []
  header.split(',').forEach((part, index) => {
    const [rawLang, ...params] = part.trim().split(';')
    const lang = rawLang?.trim().toLowerCase()
    if (!lang || lang === '*') return
    let q = 1
    for (const param of params) {
      const [key, value] = param.split('=').map((s) => s?.trim())
      if (key === 'q') {
        const parsed = Number(value)
        if (Number.isFinite(parsed)) q = parsed // malformed q → keep default 1
      }
    }
    if (q > 0) candidates.push({ lang, q, index })
  })

  candidates.sort((a, b) => b.q - a.q || a.index - b.index)

  for (const { lang } of candidates) {
    if (locales.includes(lang)) return lang
    const base = lang.split('-')[0]
    if (locales.includes(base)) return base
  }
  return defaultLocale
}
