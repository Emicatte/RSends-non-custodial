import AuthHeader from '@/components/auth/AuthHeader'
import { ContactForm } from '@/components/contact/ContactForm'

export default function ContactPage() {
  return (
    <div className="relative min-h-screen" style={{ background: '#FAF8F3' }}>
      <AuthHeader />
      <main className="min-h-screen flex items-center justify-center px-4 py-10">
        <ContactForm />
      </main>
    </div>
  )
}
