'use client'
import Link from 'next/link'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useSession } from 'next-auth/react'
import { performLogout } from '@/lib/logoutClient'

export default function AuthHeader() {
  const locale = useLocale()
  const t = useTranslations('auth')
  const { status } = useSession()
  const [signingOut, setSigningOut] = useState(false)
  const [signOutFailed, setSignOutFailed] = useState(false)
  return (
    <header className="absolute top-0 left-0 right-0 p-6 z-10 flex items-center justify-between">
      <Link
        href={`/${locale}`}
        className="inline-block text-2xl font-bold text-[#C8512C] transition-opacity hover:opacity-70"
        aria-label="Back to home"
      >
        RSends
      </Link>
      {status === 'authenticated' ? (
        <span className="flex items-center gap-3">
          {signOutFailed && (
            <span role="alert" className="text-xs text-[#C8512C]">
              {t('signOutError')}
            </span>
          )}
          <button
            type="button"
            disabled={signingOut}
            onClick={async () => {
              setSigningOut(true)
              setSignOutFailed(false)
              // Blocking logout: server session revoked first, then client
              // state cleared + redirect. Previously this never called the
              // backend at all (NextAuth-only sign-out).
              const { ok } = await performLogout({ callbackUrl: `/${locale}` })
              if (!ok) {
                setSignOutFailed(true)
                setSigningOut(false)
              }
            }}
            className="text-sm font-medium text-[#888780] hover:text-[#2C2C2A] transition-colors disabled:opacity-50"
          >
            {signingOut ? t('signingOut') : t('signOut')}
          </button>
        </span>
      ) : null}
    </header>
  )
}
