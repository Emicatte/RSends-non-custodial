'use client'

import { signIn } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'

export function GitHubSignInButton({
  callbackUrl,
  disabled,
}: {
  callbackUrl?: string
  disabled?: boolean
}) {
  const t = useTranslations('auth')
  const locale = useLocale()
  const target = callbackUrl ?? `/${locale}/app`

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => signIn('github', { callbackUrl: target })}
      className="flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
      style={{
        color: '#2C2C2A',
        border: '1px solid rgba(200,81,44,0.25)',
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.borderColor = 'rgba(200,81,44,0.5)'
      }}
      onMouseLeave={(e) => {
        if (!disabled) e.currentTarget.style.borderColor = 'rgba(200,81,44,0.25)'
      }}
    >
      <GitHubIcon />
      {t('continueWithGithub')}
    </button>
  )
}

function GitHubIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
    >
      <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58 0-.29-.01-1.05-.02-2.06-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.74.08-.73.08-.73 1.2.08 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.5.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.23-3.22-.12-.3-.54-1.52.12-3.17 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.3-1.55 3.3-1.23 3.3-1.23.66 1.65.24 2.87.12 3.17.77.84 1.23 1.91 1.23 3.22 0 4.61-2.8 5.62-5.48 5.92.43.37.81 1.1.81 2.22 0 1.6-.01 2.89-.01 3.29 0 .32.22.7.82.58A12 12 0 0 0 12 .297" />
    </svg>
  )
}
