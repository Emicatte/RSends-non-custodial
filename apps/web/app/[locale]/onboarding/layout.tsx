import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import { loginBounceUrl } from '@/lib/auth/loginBounce'
import { authOptions } from '@/lib/auth-options'

/**
 * Onboarding wizard shell. Session-required (no token → login, also enforced
 * in middleware.ts) but deliberately OUTSIDE the /app and /settings layouts:
 * the onboarding guard must never run here, or a not-yet-onboarded session
 * could never reach the pages that complete onboarding.
 */
export default async function OnboardingLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  const session = await getServerSession(authOptions)
  if (!session) {
    redirect(loginBounceUrl(locale, `/${locale}/onboarding`))
  }
  return (
    <div className="min-h-screen px-4 py-10 md:py-16" style={{ background: '#FAFAFA' }}>
      <div className="mx-auto w-full max-w-2xl">{children}</div>
    </div>
  )
}
