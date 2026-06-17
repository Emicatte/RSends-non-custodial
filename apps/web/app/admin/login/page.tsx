'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function AdminLoginPage() {
  const router = useRouter()
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [mfaRequired, setMfaRequired] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const pw = password.trim()
    if (!pw) { setError('Inserisci il token di accesso.'); return }
    const code = totp.trim()
    if (mfaRequired && !code) { setError('Inserisci il codice a 6 cifre.'); return }

    setLoading(true)
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mfaRequired ? { password: pw, totp_code: code } : { password: pw }),
      })

      if (res.status === 429) {
        const body = await res.json().catch(() => ({}))
        const retryAfter = body.retry_after ?? 60
        setError(`Troppi tentativi. Riprova tra ${retryAfter}s.`)
        setLoading(false)
        return
      }

      if (res.status === 401) {
        const body = await res.json().catch(() => ({}))
        if (body.error === 'MFA_REQUIRED') {
          // Password accepted — reveal the second-factor field and ask for the code.
          setMfaRequired(true)
          setError('')
          setLoading(false)
          return
        }
        if (body.error === 'MFA_INVALID') {
          setError('Codice 2FA non valido.')
          setLoading(false)
          return
        }
        setError('Token non valido.')
        setLoading(false)
        return
      }

      if (!res.ok) {
        setError(`Errore server (${res.status}).`)
        setLoading(false)
        return
      }

      // Cookie is set by server (httpOnly). A bootstrap (no-2FA) login returns
      // requiresSetup=true — that session can ONLY enroll TOTP, so send the admin
      // to the 2FA setup page instead of the (full-scope) transactions panel.
      const body = await res.json().catch(() => ({}))
      if (body.requiresSetup) {
        router.push('/admin/2fa-setup')
        return
      }
      router.push('/admin/transactions')
    } catch {
      setError('Errore di rete. Riprova.')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: '#FAFAFA' }}>
      {/* Ambient glow */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.07]"
          style={{ background: 'radial-gradient(circle, #C8512C 0%, transparent 70%)' }} />
        <div className="absolute bottom-0 right-1/4 w-[300px] h-[300px] rounded-full opacity-[0.04]"
          style={{ background: 'radial-gradient(circle, #C8512C 0%, transparent 70%)' }} />
      </div>

      <div className="relative z-10 w-full max-w-[380px] admin-fade-in">
        {/* Card */}
        <div className="rounded-2xl border border-black/[0.08] p-8"
          style={{ background: 'linear-gradient(145deg, rgba(255,255,255,0.95) 0%, rgba(250,250,250,0.98) 100%)', boxShadow: '0 0 80px rgba(200,81,44,0.06), 0 25px 50px rgba(0,0,0,0.08)' }}>

          {/* Logo area */}
          <div className="text-center mb-8">
            <div className="mx-auto mb-4 w-12 h-12 rounded-xl flex items-center justify-center border border-[#C8512C]/20"
              style={{ background: 'linear-gradient(135deg, rgba(200,81,44,0.15) 0%, rgba(200,81,44,0.1) 100%)' }}>
              <svg className="w-5 h-5 text-[#C8512C]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-[#0A0A0A] tracking-tight">RSends Admin</h1>
            <p className="mt-1.5 text-sm" style={{ color: 'rgba(10,10,10,0.55)' }}>Pannello di amministrazione</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="mb-5">
              <label htmlFor="admin-pw" className="block text-[11px] font-semibold uppercase tracking-widest mb-2" style={{ color: 'rgba(10,10,10,0.55)' }}>
                Token di accesso
              </label>
              <input
                id="admin-pw"
                type="password"
                autoComplete="current-password"
                placeholder="Inserisci il token"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full rounded-xl border border-black/[0.08] bg-black/[0.03] px-4 py-3 text-sm text-[#0A0A0A] placeholder-black/30 transition-all focus:border-[#C8512C]/40 focus:outline-none focus:ring-2 focus:ring-[#C8512C]/10"
              />
            </div>

            {mfaRequired && (
              <div className="mb-5">
                <label htmlFor="admin-totp" className="block text-[11px] font-semibold uppercase tracking-widest mb-2" style={{ color: 'rgba(10,10,10,0.55)' }}>
                  Codice 2FA
                </label>
                <input
                  id="admin-totp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]*"
                  maxLength={6}
                  autoFocus
                  placeholder="000000"
                  value={totp}
                  onChange={e => setTotp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="w-full rounded-xl border border-black/[0.08] bg-black/[0.03] px-4 py-3 text-sm text-[#0A0A0A] placeholder-black/30 text-center font-mono tracking-[0.4em] transition-all focus:border-[#C8512C]/40 focus:outline-none focus:ring-2 focus:ring-[#C8512C]/10"
                />
                <p className="mt-2 text-[11px]" style={{ color: 'rgba(10,10,10,0.45)' }}>
                  Password corretta. Inserisci il codice a 6 cifre dell&apos;app authenticator.
                </p>
              </div>
            )}

            {error && (
              <div className="mb-4 flex items-center gap-2 rounded-lg bg-red-500/[0.08] border border-red-500/10 px-3 py-2.5">
                <svg className="h-3.5 w-3.5 flex-shrink-0 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
                </svg>
                <p className="text-xs text-red-400">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xl py-3 text-sm font-semibold text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
              style={{
                background: 'linear-gradient(135deg, #C8512C 0%, #C8512C 100%)',
                boxShadow: loading ? 'none' : '0 4px 24px rgba(200,81,44,0.3), inset 0 1px 0 rgba(10,10,10,0.1)',
              }}
            >
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Verifica in corso...
                </span>
              ) : (mfaRequired ? 'Verifica codice' : 'Accedi')}
            </button>
          </form>

          {/* Footer inside card */}
          <div className="mt-6 pt-5 border-t border-black/[0.06] text-center">
            <p className="text-[11px]" style={{ color: 'rgba(10,10,10,0.55)' }}>Sessione protetta con cookie httpOnly</p>
          </div>
        </div>

        {/* Branding */}
        <p className="text-center mt-5 text-[11px]" style={{ color: 'rgba(10,10,10,0.35)' }}>RPagos Platform &middot; v4</p>
      </div>
    </div>
  )
}
