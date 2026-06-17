'use client'

import { useTranslations } from 'next-intl'
import { useMemo } from 'react'

const COMMON_WEAK = new Set([
  'password',
  'password1',
  'password123',
  '12345678',
  '123456789',
  '1234567890',
  'qwerty123',
  'letmein',
  'welcome',
  'admin123',
  'iloveyou',
])

function scorePassword(pwd: string): 0 | 1 | 2 | 3 | 4 {
  if (!pwd) return 0
  if (COMMON_WEAK.has(pwd.toLowerCase())) return 1
  let score = 0
  if (pwd.length >= 10) score += 1
  if (pwd.length >= 14) score += 1
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score += 1
  if (/\d/.test(pwd)) score += 1
  if (/[^A-Za-z0-9]/.test(pwd)) score += 1
  if (score > 4) score = 4
  return score as 0 | 1 | 2 | 3 | 4
}

const COLORS = ['transparent', '#C0392B', '#E67E22', '#C8B04C', '#4C9A6B']

export function PasswordStrengthMeter({ password }: { password: string }) {
  const t = useTranslations('auth.password')
  const score = useMemo(() => scorePassword(password), [password])
  const labelKey =
    score === 0
      ? 'empty'
      : score === 1
        ? 'weak'
        : score === 2
          ? 'fair'
          : score === 3
            ? 'good'
            : 'strong'

  return (
    <div aria-live="polite" className="mt-2">
      <div className="flex gap-1" role="presentation">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-1 flex-1 rounded-full transition-colors"
            style={{
              background: i <= score ? COLORS[score] : 'rgba(200,81,44,0.12)',
            }}
          />
        ))}
      </div>
      {score > 0 ? (
        <p
          className="mt-1 text-xs"
          style={{ color: score >= 3 ? '#4C9A6B' : '#888780' }}
        >
          {t(labelKey)}
        </p>
      ) : null}
    </div>
  )
}

export { scorePassword }
