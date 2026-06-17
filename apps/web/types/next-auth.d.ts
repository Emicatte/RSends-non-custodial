import 'next-auth'
import 'next-auth/jwt'

// Augments NextAuth's Session/JWT/User with the fields this app stashes on
// them. `email_verified` drives the "verify your email" banner; it is only
// ever explicitly `false` for unverified email/password users — Google/GitHub
// users are verified by construction, so it stays undefined for them.
declare module 'next-auth' {
  interface Session {
    access_token?: string
    id_token?: string
    github_access_token?: string
    email_verified?: boolean
  }

  interface User {
    access_token?: string
    email_verified?: boolean
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    access_token?: string
    id_token?: string
    github_access_token?: string
    email_verified?: boolean
  }
}
