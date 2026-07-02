'use client'
import Link from 'next/link'
import { useState } from 'react'
import { useSession } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'
import { performLogout } from '@/lib/logoutClient'

export function AuthButtons() {
  const { data: session, status } = useSession()
  const t = useTranslations('auth')
  const locale = useLocale()
  const [signingOut, setSigningOut] = useState(false)
  const [signOutFailed, setSignOutFailed] = useState(false)

  if (status === 'loading') return null

  if (status === 'authenticated') {
    const image = session?.user?.image
    return (
      <div className="flex items-center gap-2">
        {signOutFailed && (
          <span role="alert" className="text-xs text-[#C8512C]">
            {t('signOutError')}
          </span>
        )}
        {image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt="" className="h-7 w-7 rounded-full" />
        )}
        <button
          type="button"
          disabled={signingOut}
          onClick={async () => {
            setSigningOut(true)
            setSignOutFailed(false)
            // Blocking logout: the backend call revokes the Redis session and
            // expires the HttpOnly cookies — client state is cleared only if
            // that succeeds (never a silent half-logout).
            const { ok } = await performLogout()
            if (!ok) {
              setSignOutFailed(true)
              setSigningOut(false)
            }
          }}
          className="text-xs text-[#888780] transition-colors hover:text-[#C8512C] disabled:opacity-50"
        >
          {signingOut ? t('signingOut') : t('signOut')}
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <Link
        href={`/${locale}/login`}
        className="text-sm text-[#2C2C2A] transition-colors hover:text-[#C8512C] px-3 py-1.5"
      >
        {t('signIn')}
      </Link>
      <Link
        href={`/${locale}/signup`}
        className="rounded-lg bg-[#C8512C] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[#B04724]"
      >
        {t('signUp')}
      </Link>
    </div>
  )
}
