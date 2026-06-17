'use client'

import { useLocale, useTranslations } from 'next-intl'
import Link from 'next/link'
import { signIn } from 'next-auth/react'

export type LinkingScenario =
  | 'existing-google'
  | 'existing-password'
  | 'existing-github'

export function AccountLinkingModal({
  scenario,
  email,
  onClose,
}: {
  scenario: LinkingScenario
  email: string
  onClose: () => void
}) {
  const t = useTranslations('auth.linking')
  const locale = useLocale()

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-linking-title"
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(44,44,42,0.45)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6"
        style={{ border: '1px solid rgba(200,81,44,0.25)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="account-linking-title"
          className="text-lg font-semibold"
          style={{ color: '#2C2C2A' }}
        >
          {scenario === 'existing-google'
            ? t('googleTitle')
            : scenario === 'existing-github'
              ? t('githubTitle')
              : t('passwordTitle')}
        </h2>
        <p className="mt-2 text-sm" style={{ color: '#888780' }}>
          {scenario === 'existing-google'
            ? t('googleBody', { email })
            : scenario === 'existing-github'
              ? t('githubBody', { email })
              : t('passwordBody', { email })}
        </p>

        <div className="mt-5 flex flex-col gap-2">
          {scenario === 'existing-google' ? (
            <button
              type="button"
              onClick={() => signIn('google', { callbackUrl: `/${locale}/app` })}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white"
              style={{ background: '#C8512C', border: 'none', cursor: 'pointer' }}
            >
              {t('ctaGoogle')}
            </button>
          ) : scenario === 'existing-github' ? (
            <button
              type="button"
              onClick={() => signIn('github', { callbackUrl: `/${locale}/app` })}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white"
              style={{ background: '#C8512C', border: 'none', cursor: 'pointer' }}
            >
              {t('ctaGithub')}
            </button>
          ) : (
            <Link
              href={`/${locale}/login`}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white text-center"
              style={{ background: '#C8512C', textDecoration: 'none' }}
            >
              {t('ctaLogin')}
            </Link>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-white px-4 py-2 text-sm font-medium"
            style={{
              color: '#2C2C2A',
              border: '1px solid rgba(200,81,44,0.25)',
              cursor: 'pointer',
            }}
          >
            {t('ctaClose')}
          </button>
        </div>
      </div>
    </div>
  )
}
