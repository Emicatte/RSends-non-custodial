'use client'
import Link from 'next/link'
import { useLocale } from 'next-intl'

export default function AuthHeader() {
  const locale = useLocale()
  return (
    <header className="absolute top-0 left-0 right-0 p-6 z-10">
      <Link
        href={`/${locale}`}
        className="inline-block text-2xl font-bold text-[#C8512C] transition-opacity hover:opacity-70"
        aria-label="Back to home"
      >
        RSends
      </Link>
    </header>
  )
}
