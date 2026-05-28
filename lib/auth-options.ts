import type { NextAuthOptions } from 'next-auth'
import GoogleProvider from 'next-auth/providers/google'
import GitHubProvider from 'next-auth/providers/github'
import CredentialsProvider from 'next-auth/providers/credentials'
import { requireEnv } from '@/lib/env'

/**
 * NextAuth v4 options shared between the route handler and any
 * server-side caller that needs `getServerSession(authOptions)`.
 *
 * Google flow: id_token is stashed in the JWT once; the actual backend
 * session (httpOnly refresh + sid cookies + bearer access_token) is
 * established by a client-side bootstrap effect that POSTs the id_token
 * to /api/rp-auth/api/v1/auth/google so the Set-Cookie headers land in
 * the browser.
 *
 * Credentials (email+password) flow: the client POSTs email+password to
 * /api/rp-auth/api/v1/auth/login to set the httpOnly cookies and get an
 * access_token, then calls signIn('credentials', { access_token, ... }).
 * This provider verifies the token server-to-server against /auth/me
 * and seeds the JWT with access_token so downstream hooks that gate on
 * useSession().status === 'authenticated' work identically to Google.
 */

const BACKEND_URL = requireEnv('RPAGOS_BACKEND_URL')

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
      authorization: {
        params: {
          scope: 'openid email profile',
          prompt: 'select_account',
        },
      },
    }),
    GitHubProvider({
      clientId: process.env.GITHUB_CLIENT_ID ?? '',
      clientSecret: process.env.GITHUB_CLIENT_SECRET ?? '',
      authorization: {
        params: {
          scope: 'read:user user:email',
        },
      },
    }),
    CredentialsProvider({
      id: 'credentials',
      name: 'Email and password',
      credentials: {
        access_token: { type: 'text' },
        user_id: { type: 'text' },
        email: { type: 'text' },
      },
      async authorize(credentials) {
        if (!credentials?.access_token) return null
        try {
          const res = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
            headers: { Authorization: `Bearer ${credentials.access_token}` },
            cache: 'no-store',
          })
          if (!res.ok) return null
          const user = (await res.json()) as {
            id?: string
            email?: string
            display_name?: string | null
          }
          return {
            id: user.id ?? credentials.user_id ?? 'unknown',
            email: user.email ?? credentials.email ?? '',
            name: user.display_name ?? user.email ?? credentials.email ?? null,
            access_token: credentials.access_token,
          } as unknown as { id: string; email: string; name: string | null; access_token: string }
        } catch {
          return null
        }
      },
    }),
  ],
  session: { strategy: 'jwt', maxAge: 30 * 60 },
  callbacks: {
    async jwt({ token, account, user, trigger, session }) {
      if (account?.provider === 'google' && account.id_token) {
        ;(token as Record<string, unknown>).id_token = account.id_token
      }
      if (account?.provider === 'github' && account.access_token) {
        ;(token as Record<string, unknown>).github_access_token = account.access_token
      }
      if (
        account?.provider === 'credentials' &&
        user &&
        (user as unknown as Record<string, unknown>).access_token
      ) {
        ;(token as Record<string, unknown>).access_token = (user as unknown as Record<string, unknown>).access_token
        ;(token as Record<string, unknown>).id_token = undefined
        ;(token as Record<string, unknown>).github_access_token = undefined
      }
      if (trigger === 'update' && session && (session as Record<string, unknown>).access_token) {
        ;(token as Record<string, unknown>).access_token = (session as Record<string, unknown>).access_token
        ;(token as Record<string, unknown>).id_token = undefined
        ;(token as Record<string, unknown>).github_access_token = undefined
      }
      return token
    },
    async session({ session, token }) {
      ;(session as unknown as Record<string, unknown>).id_token = (token as Record<string, unknown>).id_token
      ;(session as unknown as Record<string, unknown>).github_access_token = (token as Record<string, unknown>).github_access_token
      ;(session as unknown as Record<string, unknown>).access_token = (token as Record<string, unknown>).access_token
      return session
    },
  },
}
