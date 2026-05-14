'use client'

import { motion } from 'framer-motion'
import { C, EASE } from '@/app/designTokens'

export default function AboutOverlay() {
  const stats = [
    { label: 'Mainnet Contracts', value: 2 },
    { label: 'Basescan Verified', value: 100, suffix: '%' },
    { label: 'Chains Supported', value: 3, suffix: '+' },
    { label: 'API Endpoints', value: 8, suffix: '+' },
  ]

  return (
    <div>
      {/* ═══ A) Animated Headline ═══ */}
      <motion.h2
        style={{ fontFamily: C.D, fontSize: 24, fontWeight: 600, color: C.text, marginBottom: 24, lineHeight: 1.3 }}
      >
        {'Built by one. Trusted by design.'.split('').map((char, i) => (
          <motion.span
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.025, duration: 0.3, ease: EASE }}
          >
            {char}
          </motion.span>
        ))}
      </motion.h2>

      {/* ═══ B) Mission Block ═══ */}
      <div style={{ marginBottom: 28 }}>
        {[
          'I built RSends because I got tired of watching European businesses struggle with crypto payments. Either you use a centralized gateway that holds your funds hostage, or you go full DeFi and pray the taxman doesn\'t knock.',
          'Every transaction goes through a compliance Oracle before anything moves on-chain. Not a post-hoc audit. Not a checkbox. Actual pre-execution verification, enforced at the smart contract level.',
          'Base L2 keeps gas under $0.05. Settlement in 2 seconds. Compliance built in from day one. Because in this space, "we\'ll add compliance later" is how companies get shut down.',
        ].map((p, i) => (
          <motion.p
            key={i}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.8 + i * 0.15, duration: 0.5, ease: EASE }}
            style={{ fontFamily: C.S, fontSize: 13, color: C.sub, lineHeight: 1.7, marginBottom: 14 }}
          >
            {p}
          </motion.p>
        ))}
      </div>

      {/* ═══ C) Founder Card ═══ */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.3, duration: 0.5, ease: EASE }}
        style={{
          padding: '22px 20px', borderRadius: 16, marginBottom: 28,
          background: 'linear-gradient(135deg, rgba(59,130,246,0.06) 0%, rgba(200,81,44,0.06) 50%, rgba(255,76,106,0.04) 100%)',
          border: `1px solid ${C.border}`, position: 'relative', overflow: 'hidden',
        }}
      >
        {/* Mesh gradient background */}
        <div style={{
          position: 'absolute', top: -40, right: -40, width: 120, height: 120,
          background: 'radial-gradient(circle, rgba(59,130,246,0.12) 0%, transparent 70%)',
          borderRadius: '50%', pointerEvents: 'none',
        }} />
        <div style={{ position: 'relative' }}>
          <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.blue, textTransform: 'uppercase' as const, letterSpacing: '0.1em', marginBottom: 6 }}>
            Founder & Solo Developer
          </div>
          <div style={{ fontFamily: C.S, fontSize: 13, color: C.sub, lineHeight: 1.6, marginBottom: 14 }}>
            One person, full stack. Solidity contracts, React frontend, FastAPI backend, compliance engine. No team of 50 — just obsessive attention to getting payments right.
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const }}>
            {['Solidity', 'Next.js', 'FastAPI', 'Foundry'].map((tech, i) => (
              <motion.span
                key={tech}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 1.6 + i * 0.1, duration: 0.3 }}
                style={{
                  padding: '4px 10px', borderRadius: 6,
                  background: 'rgba(10,10,10,0.04)', border: `1px solid ${C.border}`,
                  fontFamily: C.M, fontSize: 9, color: C.dim,
                }}
              >
                {tech}
              </motion.span>
            ))}
            <a
              href="https://github.com/Emicatte/feerouter-dapp"
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: 'flex', alignItems: 'center', marginLeft: 4 }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill={C.dim}>
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
              </svg>
            </a>
          </div>
        </div>
      </motion.div>

      {/* ═══ D) Stats Counters ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {stats.map((s, i) => (
          <motion.div
            key={s.label}
            initial={{ opacity: 0, y: 10 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.1, duration: 0.4, ease: EASE }}
            style={{
              padding: '16px 10px', borderRadius: 14, textAlign: 'center' as const,
              background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
            }}
          >
            <div style={{ fontFamily: C.D, fontSize: 24, fontWeight: 800, color: C.text }}>
              {s.value}{s.suffix || ''}
            </div>
            <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 4 }}>
              {s.label}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
