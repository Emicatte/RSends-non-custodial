import { Suspense } from 'react'
import { LoginForm } from '@/components/auth/LoginForm'
import AuthHeader from '@/components/auth/AuthHeader'

export default function LoginPage() {
  return (
    <div className="relative min-h-screen" style={{ background: '#FAF8F3' }}>
      <AuthHeader />
      <main className="min-h-screen flex items-center justify-center px-4 py-10">
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </main>
    </div>
  )
}
