'use client'
import Link from 'next/link'
import { useLocale } from 'next-intl'
import { useSession, signOut } from 'next-auth/react'

export default function AuthHeader() {
  const locale = useLocale()
  const { status } = useSession()
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
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: `/${locale}` })}
          className="text-sm font-medium text-[#888780] hover:text-[#2C2C2A] transition-colors"
        >
          Log out
        </button>
      ) : null}
    </header>
  )
}
