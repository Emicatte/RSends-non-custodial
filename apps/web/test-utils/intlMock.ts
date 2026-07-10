/**
 * Shared next-intl mock for component tests.
 *
 * Usage (per test file):
 *   jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())
 *
 * `useTranslations(ns)` resolves keys against messages/en.json and THROWS on
 * any missing key — every rendered component doubles as an i18n-key guard.
 * Minimal `{param}` interpolation matches the ICU params the pay copy uses.
 */

export function intlModuleMock(locale = 'en') {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const messages = require(`@/messages/${locale}.json`)

  const resolve = (namespace: string, key: string): string => {
    const path = namespace ? `${namespace}.${key}` : key
    const value = path
      .split('.')
      .reduce<unknown>(
        (node, part) => (node as Record<string, unknown> | undefined)?.[part],
        messages,
      )
    if (typeof value !== 'string') {
      throw new Error(`Missing message ${path}`)
    }
    return value
  }

  const interpolate = (
    template: string,
    values?: Record<string, unknown>,
  ): string =>
    template.replace(/\{(\w+)\}/g, (match, name) =>
      values && name in values ? String(values[name]) : match,
    )

  return {
    useLocale: () => locale,
    useTranslations: (namespace: string) => {
      const t = (key: string, values?: Record<string, unknown>) =>
        interpolate(resolve(namespace, key), values)
      return t
    },
  }
}
