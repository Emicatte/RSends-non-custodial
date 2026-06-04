'use client'

import { useCallback, useState } from 'react'

export interface CheckEmailResult {
  exists: boolean
  has_google: boolean
  has_password: boolean
  has_github: boolean
}

export type AccountType = 'individual' | 'merchant'

export interface SignupInput {
  email: string
  password: string
  first_name: string
  last_name: string
  date_of_birth: string // YYYY-MM-DD
  country_of_residence: string // ISO 3166-1 alpha-2
  account_type: AccountType
  terms_accepted: boolean
  newsletter_opt_in: boolean
  turnstile_token: string
  locale?: string
}

export interface SignupResult {
  user_id: string
  email: string
  email_verified: boolean
  account_type: AccountType
  display_name: string | null
  created_at: string
}

export interface EmailAuthErrorShape {
  code: string
  message?: string
  status?: number
  retry_after?: string | null
}

const BASE = '/api/rp-auth/api/v1/auth'

async function extractError(res: Response): Promise<EmailAuthErrorShape> {
  let code = 'unknown'
  let message: string | undefined
  try {
    const body = (await res.json()) as {
      detail?:
        | { code?: string; message?: string }
        | Array<{ msg?: string; loc?: unknown[] }>
        | string
      code?: string
    }
    if (Array.isArray(body.detail)) {
      // FastAPI/Pydantic 422 validation error → extract the validator's code
      // (e.g. "Value error, under_18" → "under_18").
      const first = body.detail[0]
      const raw = typeof first?.msg === 'string' ? first.msg : ''
      code = raw.replace(/^Value error,\s*/, '').trim() || 'validation_error'
    } else if (typeof body.detail === 'object' && body.detail) {
      code = body.detail.code ?? code
      message = body.detail.message
    } else if (typeof body.detail === 'string') {
      message = body.detail
    } else if (body.code) {
      code = body.code
    }
  } catch {
    // body not JSON
  }
  return {
    code,
    message,
    status: res.status,
    retry_after: res.headers.get('Retry-After'),
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await extractError(res)
    throw err
  }
  return res.json() as Promise<T>
}

export function useEmailAuth() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<EmailAuthErrorShape | null>(null)

  const signup = useCallback(async (input: SignupInput): Promise<SignupResult> => {
    setLoading(true)
    setError(null)
    try {
      // Dedicated route: verifies Turnstile server-side, then forwards to the
      // backend signup. NOT the generic rp-auth proxy.
      const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(input),
      })
      if (!res.ok) {
        throw await extractError(res)
      }
      return (await res.json()) as SignupResult
    } catch (e) {
      setError(e as EmailAuthErrorShape)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const verifyEmail = useCallback(async (token: string): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      await postJson<{ status: string; email: string }>('/verify-email', { token })
    } catch (e) {
      setError(e as EmailAuthErrorShape)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const resendVerification = useCallback(async (email: string): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      await postJson<{ status: string }>('/resend-verification', { email })
    } catch (e) {
      setError(e as EmailAuthErrorShape)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const requestPasswordReset = useCallback(async (email: string): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      await postJson<{ status: string; message: string }>(
        '/request-password-reset',
        { email },
      )
    } catch (e) {
      setError(e as EmailAuthErrorShape)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const resetPassword = useCallback(
    async (token: string, new_password: string): Promise<void> => {
      setLoading(true)
      setError(null)
      try {
        await postJson<{ status: string; email: string }>('/reset-password', {
          token,
          new_password,
        })
      } catch (e) {
        setError(e as EmailAuthErrorShape)
        throw e
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  const checkEmail = useCallback(async (email: string): Promise<CheckEmailResult> => {
    const res = await fetch(
      `${BASE}/check-email?email=${encodeURIComponent(email)}`,
      { credentials: 'include' },
    )
    if (!res.ok) {
      const err = await extractError(res)
      throw err
    }
    return res.json() as Promise<CheckEmailResult>
  }, [])

  return {
    loading,
    error,
    clearError: () => setError(null),
    signup,
    verifyEmail,
    resendVerification,
    requestPasswordReset,
    resetPassword,
    checkEmail,
  }
}
