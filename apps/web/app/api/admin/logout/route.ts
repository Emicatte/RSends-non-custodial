import { NextResponse } from 'next/server'

const COOKIE_NAME = 'admin_session'

export async function POST(req: Request) {
  // Revoke the token from the in-memory store
  const cookieHeader = req.headers.get('cookie') || ''
  const match = cookieHeader.match(new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`))
  const token = match ? decodeURIComponent(match[1]) : ''

  if (token) {
    const { revokeToken } = await import('@/lib/auth/adminTokens')
    revokeToken(token)
  }

  const res = NextResponse.json({ status: 'ok' })
  res.cookies.set(COOKIE_NAME, '', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'strict',
    path: '/',
    maxAge: 0,
  })

  return res
}
