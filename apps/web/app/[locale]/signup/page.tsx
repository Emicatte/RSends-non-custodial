import { SignupForm } from '@/components/auth/SignupForm'
import AuthHeader from '@/components/auth/AuthHeader'

export default function SignupPage() {
  return (
    <div className="relative min-h-screen" style={{ background: '#FAF8F3' }}>
      <AuthHeader />
      <main className="min-h-screen flex items-center justify-center px-4 py-10">
        <SignupForm />
      </main>
    </div>
  )
}
