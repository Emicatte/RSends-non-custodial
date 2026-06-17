'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'

interface SetupData {
  secret: string
  otpauthUrl: string
  qrDataUrl: string
  instructions: string
}

export default function Admin2faSetupPage() {
  const router = useRouter()
  const [data, setData] = useState<SetupData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/admin/2fa/setup', { method: 'POST' })
      if (res.status === 401) {
        // Session missing/expired — back to login.
        router.push('/admin/login')
        return
      }
      if (!res.ok) {
        setError(`Errore server (${res.status}).`)
        setLoading(false)
        return
      }
      const body: SetupData = await res.json()
      setData(body)
      setLoading(false)
    } catch {
      setError('Errore di rete. Riprova.')
      setLoading(false)
    }
  }, [router])

  useEffect(() => { load() }, [load])

  async function copySecret() {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable — no-op, the secret is visible on screen
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: '#FAFAFA' }}>
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.07]"
          style={{ background: 'radial-gradient(circle, #C8512C 0%, transparent 70%)' }} />
      </div>

      <div className="relative z-10 w-full max-w-[420px] admin-fade-in">
        <div className="rounded-2xl border border-black/[0.08] p-8"
          style={{ background: 'linear-gradient(145deg, rgba(255,255,255,0.95) 0%, rgba(250,250,250,0.98) 100%)', boxShadow: '0 0 80px rgba(200,81,44,0.06), 0 25px 50px rgba(0,0,0,0.08)' }}>

          <div className="text-center mb-6">
            <h1 className="text-xl font-bold text-[#0A0A0A] tracking-tight">Configura 2FA</h1>
            <p className="mt-1.5 text-sm" style={{ color: 'rgba(10,10,10,0.55)' }}>RSends Admin &middot; autenticazione a due fattori</p>
          </div>

          {loading && (
            <div className="flex items-center justify-center py-10">
              <svg className="h-5 w-5 animate-spin text-[#C8512C]" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          )}

          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg bg-red-500/[0.08] border border-red-500/10 px-3 py-2.5">
              <p className="text-xs text-red-400">{error}</p>
            </div>
          )}

          {!loading && data && (
            <>
              {/* QR */}
              <div className="flex justify-center mb-5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={data.qrDataUrl} alt="QR code TOTP" width={200} height={200}
                  className="rounded-xl border border-black/[0.08] bg-white p-2" />
              </div>

              {/* Secret (backup) */}
              <label className="block text-[11px] font-semibold uppercase tracking-widest mb-2" style={{ color: 'rgba(10,10,10,0.55)' }}>
                Secret (backup manuale)
              </label>
              <button
                type="button"
                onClick={copySecret}
                className="w-full rounded-xl border border-black/[0.08] bg-black/[0.03] px-4 py-3 text-xs font-mono text-[#0A0A0A] break-all text-left transition-colors hover:bg-black/[0.05] cursor-pointer"
                title="Clicca per copiare"
              >
                {data.secret}
                <span className="ml-2 text-[#C8512C]">{copied ? '✓ copiato' : '⧉'}</span>
              </button>

              {/* Instructions */}
              <div className="mt-5 rounded-xl bg-[#C8512C]/[0.05] border border-[#C8512C]/15 px-4 py-3">
                <p className="text-[11px] leading-relaxed" style={{ color: 'rgba(10,10,10,0.7)' }}>
                  {data.instructions}
                </p>
              </div>

              <button
                type="button"
                onClick={() => router.push('/admin/login')}
                className="mt-6 w-full rounded-xl py-3 text-sm font-semibold text-white transition-all active:scale-[0.98]"
                style={{ background: 'linear-gradient(135deg, #C8512C 0%, #C8512C 100%)', boxShadow: '0 4px 24px rgba(200,81,44,0.3), inset 0 1px 0 rgba(10,10,10,0.1)' }}
              >
                Ho configurato — torna al login
              </button>
            </>
          )}

          <div className="mt-6 pt-5 border-t border-black/[0.06] text-center">
            <p className="text-[11px]" style={{ color: 'rgba(10,10,10,0.55)' }}>
              Il secret va salvato in <span className="font-mono">ADMIN_TOTP_SECRET</span> e richiede redeploy.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
