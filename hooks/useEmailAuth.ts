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
  display_name: string
  terms_accepted: boolean
  account_type: AccountType
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
      detail?: { code?: string; message?: string } | string
      code?: string
    }
    if (typeof body.detail === 'object' && body.detail) {
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
      return await postJson<SignupResult>('/signup', input)
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
