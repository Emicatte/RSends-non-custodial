'use client'
import Link from 'next/link'
import { signOut, useSession } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'

export function AuthButtons() {
  const { data: session, status } = useSession()
  const t = useTranslations('auth')
  const locale = useLocale()

  if (status === 'loading') return null

  if (status === 'authenticated') {
    const image = session?.user?.image
    return (
      <div className="flex items-center gap-2">
        {image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt="" className="h-7 w-7 rounded-full" />
        )}
        <button
          type="button"
          onClick={() => {
            void signOut({ redirect: false })
            // Best-effort backend logout (clears Redis session + cookies).
            void fetch('/api/rp-auth/api/v1/auth/logout', {
              method: 'POST',
              credentials: 'include',
            })
          }}
          className="text-xs text-[#888780] transition-colors hover:text-[#C8512C]"
        >
          {t('signOut')}
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
