'use client'

import { signIn } from 'next-auth/react'
import { useLocale, useTranslations } from 'next-intl'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useState } from 'react'
import {
  classifyLoginFailure,
  logLoginFailure,
  newCorrelationId,
  type LoginFailure,
} from '@/lib/auth/loginFailure'
import { useEmailAuth, type EmailAuthErrorShape } from '@/hooks/useEmailAuth'
import { EmailAuthError } from './EmailAuthError'

/**
 * Client-side backstop only. The rp-auth proxy already aborts upstream at 25s
 * and its route caps at maxDuration=30, so in every normal outage the proxy's
 * own 502 arrives first and is reported as an upstream failure. This timer
 * exists for the case where the proxy itself never answers — without it the
 * browser waits indefinitely and the user is told nothing.
 */
const LOGIN_TIMEOUT_MS = 35_000

const INPUT_STYLE: React.CSSProperties = {
  border: '1px solid rgba(200,81,44,0.25)',
  borderRadius: 10,
  padding: '10px 12px',
  fontSize: 14,
  color: '#2C2C2A',
  background: '#fff',
  width: '100%',
  outline: 'none',
}

interface LoginSuccessBody {
  access_token: string
  expires_in: number
  user_id: string
  email: string
  email_verified: boolean
}

async function backendLogin(
  email: string,
  password: string,
  correlationId: string,
): Promise<LoginSuccessBody> {
  const controller = new AbortController()
  const timer = setTimeout(
    () => controller.abort(new DOMException('login timed out', 'TimeoutError')),
    LOGIN_TIMEOUT_MS,
  )

  let res: Response
  try {
    res = await fetch('/api/rp-auth/api/v1/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Joins this attempt to the backend request log and, on a successful
        // login, to auth_audit_log.correlation_id.
        'X-Request-ID': correlationId,
        'X-Correlation-ID': correlationId,
      },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let code = 'unknown'
    let message: string | undefined
    try {
      const body = (await res.json()) as {
        detail?: { code?: string; message?: string }
      }
      if (body.detail) {
        code = body.detail.code ?? code
        message = body.detail.message
      }
    } catch {
      // Unparseable error body — the status alone classifies it.
    }
    const err: EmailAuthErrorShape = {
      code,
      message,
      status: res.status,
      retry_after: res.headers.get('Retry-After'),
    }
    throw err
  }

  try {
    return (await res.json()) as LoginSuccessBody
  } catch {
    // The server answered, but not with the login payload. That is an upstream
    // malfunction — the one case besides a 5xx that honestly is "unavailable".
    throw { code: 'auth_unavailable', status: res.status } as EmailAuthErrorShape
  }
}

export function LoginForm() {
  const t = useTranslations('auth.login')
  const tCommon = useTranslations('auth')
  const locale = useLocale()
  const router = useRouter()
  const params = useSearchParams()
  const { resendVerification } = useEmailAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  // Forced-logout bounces (dead session detected post-login) land here with
  // ?error=session_expired. Whitelisted: the param feeds a translation key,
  // so an arbitrary value must never reach EmailAuthError.
  const [error, setError] = useState<
    (EmailAuthErrorShape & { correlationId?: string }) | null
  >(() =>
    params.get('error') === 'session_expired' ? { code: 'session_expired' } : null,
  )
  const [resendState, setResendState] = useState<'idle' | 'sending' | 'sent'>('idle')

  /** Single exit for every failure: log it, then show it. Never retries. */
  const fail = (failure: LoginFailure) => {
    logLoginFailure(failure)
    setError(failure)
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResendState('idle')
    setLoading(true)
    const correlationId = newCorrelationId()
    try {
      const login = await backendLogin(
        email.trim().toLowerCase(),
        password,
        correlationId,
      )
      const res = await signIn('credentials', {
        redirect: false,
        access_token: login.access_token,
        user_id: login.user_id,
        email: login.email,
      })
      if (!res || res.error) {
        // The backend accepted the credentials and issued a session; only the
        // NextAuth bridge (which re-verifies the token against /auth/me)
        // failed. Calling this "service unavailable" would be false — the
        // service answered, and it said yes.
        fail({ code: 'session_bridge_failed', correlationId })
        return
      }
      const redirect = params.get('redirect') ?? `/${locale}/app`
      router.push(redirect)
    } catch (err) {
      fail(classifyLoginFailure(err, correlationId))
    } finally {
      setLoading(false)
    }
  }

  const onResend = async () => {
    const value = email.trim().toLowerCase()
    if (!value) return
    setResendState('sending')
    try {
      await resendVerification(value)
      setResendState('sent')
    } catch {
      setResendState('idle')
    }
  }

  const canSubmit = email.length > 3 && password.length > 0 && !loading

  return (
    <div className="w-full max-w-md">
      <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
        {t('title')}
      </h1>
      <p className="mt-1 text-sm" style={{ color: '#888780' }}>
        {t('subtitle')}
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('emailLabel')}
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={INPUT_STYLE}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('passwordLabel')}
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={INPUT_STYLE}
          />
        </label>

        <div className="flex justify-end">
          <Link
            href={`/${locale}/forgot-password`}
            className="text-xs"
            style={{ color: '#C8512C', textDecoration: 'none' }}
          >
            {t('forgotLink')}
          </Link>
        </div>

        {error ? (
          <>
            <EmailAuthError
              code={error.code}
              message={error.message}
              retryAfter={error.retry_after}
              correlationId={error.correlationId}
            />
            {error.code === 'email_not_verified' ? (
              <button
                type="button"
                onClick={onResend}
                disabled={resendState === 'sending'}
                className="rounded-lg bg-white px-3 py-1.5 text-xs self-start"
                style={{
                  color: '#C8512C',
                  border: '1px solid rgba(200,81,44,0.25)',
                  cursor: 'pointer',
                }}
              >
                {resendState === 'sent' ? t('resendSent') : t('resendVerification')}
              </button>
            ) : null}
          </>
        ) : null}

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          style={{ background: '#C8512C', border: 'none' }}
        >
          {loading ? t('submitLoading') : t('submit')}
        </button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: '#888780' }}>
        {tCommon('noAccount')}{' '}
        <Link
          href={`/${locale}/signup`}
          style={{ color: '#C8512C', textDecoration: 'none' }}
        >
          {tCommon('signUp')}
        </Link>
      </p>
    </div>
  )
}
