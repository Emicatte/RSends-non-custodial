'use client'

import { useLocale } from 'next-intl'
import { useRouter, usePathname } from '@/i18n/navigation'
import { useState, useTransition } from 'react'
import { C } from '@/app/designTokens'
import type { Locale } from '@/i18n/routing'

const LOCALES: { code: Locale; label: string; flag: string }[] = [
  { code: 'en', label: 'English', flag: 'EN' },
  { code: 'it', label: 'Italiano', flag: 'IT' },
  { code: 'es', label: 'Español', flag: 'ES' },
  { code: 'fr', label: 'Français', flag: 'FR' },
  { code: 'de', label: 'Deutsch', flag: 'DE' },
]

export default function LanguageSwitcher() {
  const locale = useLocale()
  const router = useRouter()
  const pathname = usePathname()
  const [isPending, startTransition] = useTransition()
  const [open, setOpen] = useState(false)

  const current = LOCALES.find((l) => l.code === locale) ?? LOCALES[0]

  const switchLocale = (next: Locale) => {
    const search = typeof window !== 'undefined' ? window.location.search : ''
    const hash = typeof window !== 'undefined' ? window.location.hash : ''
    startTransition(() => {
      router.replace(pathname + search + hash, { locale: next })
      setOpen(false)
    })
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(!open)}
        disabled={isPending}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 10px',
          background: 'transparent',
          border: 'none',
          borderRadius: 8,
          cursor: 'pointer',
          fontFamily: C.D,
          fontSize: 12,
          fontWeight: 500,
          color: C.text,
          transition: 'background 0.2s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(10,10,10,0.05)' }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
      >
        <span style={{ fontFamily: C.M, fontSize: 10, opacity: 0.6 }}>{current.flag}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M2.5 3.75L5 6.25L7.5 3.75" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {open && (
        <>
          <div
            onClick={() => setOpen(false)}
            style={{ position: 'fixed', inset: 0, zIndex: 1040 }}
          />
          <div style={{
            position: 'absolute',
            right: 0,
            top: '100%',
            marginTop: 6,
            width: 160,
            background: '#fff',
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
            zIndex: 1050,
            overflow: 'hidden',
          }}>
            {LOCALES.map((l) => (
              <button
                key={l.code}
                onClick={() => switchLocale(l.code)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '10px 14px',
                  border: 'none',
                  cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 10,
                  fontFamily: C.D,
                  fontSize: 13,
                  fontWeight: l.code === locale ? 600 : 400,
                  color: l.code === locale ? C.purple : C.text,
                  background: l.code === locale ? `${C.purple}08` : 'transparent',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) => { if (l.code !== locale) e.currentTarget.style.background = 'rgba(10,10,10,0.04)' }}
                onMouseLeave={(e) => { if (l.code !== locale) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ fontFamily: C.M, fontSize: 10, opacity: 0.5 }}>{l.flag}</span>
                <span>{l.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
