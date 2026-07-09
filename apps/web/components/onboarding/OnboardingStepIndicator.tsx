'use client'

/**
 * Wizard step indicator: Account -> Verify email -> Company info -> Dashboard.
 * Static markup, current-step highlight only — no animation.
 */

import { useTranslations } from 'next-intl'

const STEPS = ['account', 'verifyEmail', 'companyInfo', 'dashboard'] as const

export type OnboardingStep = (typeof STEPS)[number]

export function OnboardingStepIndicator({ current }: { current: OnboardingStep }) {
  const t = useTranslations('onboarding.steps')
  const currentIndex = STEPS.indexOf(current)

  return (
    <ol className="flex items-center justify-center gap-2 md:gap-4 flex-wrap" aria-label="onboarding">
      {STEPS.map((step, i) => {
        const isCurrent = i === currentIndex
        const isDone = i < currentIndex
        return (
          <li key={step} className="flex items-center gap-2 md:gap-4">
            <span
              className="flex items-center gap-2 text-xs md:text-sm"
              aria-current={isCurrent ? 'step' : undefined}
              style={{
                color: isCurrent ? '#0A0A0A' : isDone ? '#C8512C' : '#888780',
                fontWeight: isCurrent ? 600 : 400,
              }}
            >
              <span
                className="inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px]"
                style={{
                  borderColor: isCurrent || isDone ? '#C8512C' : '#DDDCD6',
                  background: isDone ? '#C8512C' : 'transparent',
                  color: isDone ? '#FFFFFF' : undefined,
                }}
              >
                {i + 1}
              </span>
              {t(step)}
            </span>
            {i < STEPS.length - 1 && (
              <span aria-hidden="true" style={{ color: '#DDDCD6' }}>
                /
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
