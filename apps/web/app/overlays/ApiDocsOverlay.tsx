'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { C } from '@/app/designTokens'

const fadeUp = {
  initial: { opacity: 0, y: 30 } as const,
  whileInView: { opacity: 1, y: 0 } as const,
  viewport: { once: true, margin: '-60px' },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] },
}

const cardStyle: React.CSSProperties = {
  background: 'rgba(10,10,10,0.5)',
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: 28,
  backdropFilter: 'blur(12px)',
  transition: 'border-color 0.2s',
}

const codeBlockStyle: React.CSSProperties = {
  background: '#FAFAFA',
  border: `1px solid ${C.border}`,
  borderRadius: 12,
  padding: '20px 24px',
  fontFamily: C.M,
  fontSize: 13,
  lineHeight: 1.7,
  overflowX: 'auto',
  margin: 0,
}

const dividerStyle: React.CSSProperties = {
  width: '100%', height: 1,
  background: 'linear-gradient(90deg, transparent, rgba(10,10,10,0.06) 20%, rgba(10,10,10,0.06) 80%, transparent)',
  margin: '80px 0',
}

function HoverCard({ children, style, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  const [hov, setHov] = useState(false)
  return (
    <div
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        ...cardStyle, ...style,
        borderColor: hov ? 'rgba(10,10,10,0.12)' : C.border,
      }}
      {...rest}
    >{children}</div>
  )
}

function SLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: C.M, fontSize: 11, fontWeight: 600, color: C.blue,
      letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 14,
    }}>{children}</div>
  )
}

function STitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontFamily: C.D, fontSize: 'clamp(26px, 4vw, 36px)', fontWeight: 700,
      color: C.text, lineHeight: 1.2, margin: '0 0 40px',
    }}>{children}</h2>
  )
}

function Cmt({ children }: { children: string }) {
  return <span style={{ color: C.dim }}>{children}</span>
}
function Kw({ children }: { children: string }) {
  return <span style={{ color: C.blue }}>{children}</span>
}
function Str({ children }: { children: string }) {
  return <span style={{ color: C.green }}>{children}</span>
}
function Punc({ children }: { children: string }) {
  return <span style={{ color: C.sub }}>{children}</span>
}

function IconCode({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M12 10L6 16L12 22" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M20 10L26 16L20 22" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconSplit({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 6V14M16 14L8 22M16 14L24 22" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconBell({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 4C12 4 9 7 9 11V18L6 22H26L23 18V11C23 7 20 4 16 4Z" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
      <path d="M13 22V23C13 24.7 14.3 26 16 26C17.7 26 19 24.7 19 23V22" stroke={color} strokeWidth="2"/>
    </svg>
  )
}

function IconGlobe({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="10" stroke={color} strokeWidth="2"/>
      <path d="M6 16H26M16 6C19 10 19 22 16 26M16 6C13 10 13 22 16 26" stroke={color} strokeWidth="1.5"/>
    </svg>
  )
}

function IconShield({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 4L6 9V16C6 22 10 27 16 28C22 27 26 22 26 16V9L16 4Z" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
      <path d="M12 16L15 19L21 13" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconLock({ color = C.purple, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect x="8" y="14" width="16" height="12" rx="3" stroke={color} strokeWidth="2"/>
      <path d="M12 14V10C12 7.8 13.8 6 16 6C18.2 6 20 7.8 20 10V14" stroke={color} strokeWidth="2"/>
      <circle cx="16" cy="20" r="2" fill={color}/>
    </svg>
  )
}

function IconGauge({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M6 22A10 10 0 0126 22" stroke={color} strokeWidth="2" strokeLinecap="round"/>
      <path d="M16 22L20 12" stroke={color} strokeWidth="2" strokeLinecap="round"/>
      <circle cx="16" cy="22" r="2" fill={color}/>
    </svg>
  )
}

function IconTarget({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="10" stroke={color} strokeWidth="2"/>
      <circle cx="16" cy="16" r="6" stroke={color} strokeWidth="1.5"/>
      <circle cx="16" cy="16" r="2" fill={color}/>
    </svg>
  )
}

function IconDoc({ color = C.amber, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect x="7" y="4" width="18" height="24" rx="3" stroke={color} strokeWidth="2"/>
      <path d="M11 10H21M11 14H21M11 18H17" stroke={color} strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  )
}

function useIsMobile(bp = 768) {
  const [m, setM] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`)
    setM(mq.matches)
    const h = (e: MediaQueryListEvent) => setM(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [bp])
  return m
}

export default function ApiDocsOverlay({ onClose, onGoToCommand }: { onClose: () => void; onGoToCommand: () => void }) {
  const isMobile = useIsMobile()

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', h)
    }
  }, [onClose])

  const steps = [
    { num: '01', title: 'Create a Payment Intent', desc: 'POST to /api/v1/merchant/payment-intent with amount, currency, chain, and webhook URL. RSends returns an intent ID and a deposit address.' },
    { num: '02', title: 'Customer Sends Crypto', desc: 'Customer sends to the generated deposit address. Any supported chain — EVM, Tron, or Solana.' },
    { num: '03', title: 'RSends Matches & Splits', desc: 'The matching engine identifies the payment. AML screens run automatically. Splits execute deterministically.' },
    { num: '04', title: 'Webhook Fires', desc: 'Your endpoint receives a typed, HMAC-verified event with the full result. Built-in retry on failure.' },
  ]

  const features = [
    { icon: <IconCode color={C.blue} />, title: 'Payment Intents', desc: 'Create intents with amount, currency, chain. Get a deposit address back.' },
    { icon: <IconBell color={C.blue} />, title: 'Webhooks', desc: 'Typed events, HMAC-verified signatures, automatic retry with exponential backoff.' },
    { icon: <IconGlobe color={C.green} />, title: 'Multi-Chain', desc: 'EVM (Base, Ethereum, Arbitrum, Optimism) + Tron + Solana. Same API.' },
    { icon: <IconSplit color={C.blue} />, title: 'Split Routing', desc: 'Define splits in basis points. Execution is deterministic and atomic.' },
    { icon: <IconShield color={C.green} />, title: 'AML Screening', desc: '3-level screening: address check, transaction monitoring, and reporting.' },
    { icon: <IconLock color={C.purple} />, title: 'Idempotency', desc: 'Built-in deduplication. Safe to retry any request without double-execution.' },
  ]

  const trustItems = [
    { icon: <IconGauge color={C.blue} />, label: 'Stress-tested throughput' },
    { icon: <IconTarget color={C.green} />, label: '0 duplicate execution' },
    { icon: <IconShield color={C.green} />, label: 'Deterministic splitting' },
    { icon: <IconDoc color={C.amber} />, label: 'Audit-ready logs' },
  ]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: C.bg, overflowY: 'auto', overflowX: 'hidden',
      }}
    >
      {/* Sticky nav bar */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: isMobile ? '14px 16px' : '16px 32px',
        background: 'rgba(250,250,250,0.8)',
        backdropFilter: 'blur(12px)',
        borderBottom: `1px solid ${C.border}`,
      }}>
        <button
          onClick={onClose}
          onMouseEnter={e => (e.currentTarget.style.color = C.text)}
          onMouseLeave={e => (e.currentTarget.style.color = C.sub)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'none', border: 'none', cursor: 'pointer',
            color: C.sub, fontFamily: C.D, fontSize: 14, transition: 'color 0.15s',
          }}
        >← Back to RSends</button>
        <button onClick={onClose} style={{
          background: 'rgba(10,10,10,0.08)', border: 'none',
          borderRadius: '50%', width: 36, height: 36, cursor: 'pointer',
          color: C.sub, fontSize: 18, display: 'grid', placeItems: 'center',
          transition: 'background 0.15s',
        }}>×</button>
      </div>

      {/* Content */}
      <div style={{
        maxWidth: 1100, margin: '0 auto',
        padding: isMobile ? '0 20px 80px' : '0 32px 100px',
      }}>

        {/* Hero */}
        <motion.div {...fadeUp} style={{
          textAlign: 'center',
          padding: isMobile ? '60px 0 0' : '80px 0 0',
        }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
            <IconCode color={C.blue} size={44} />
            <h1 style={{
              fontFamily: C.D, fontSize: 'clamp(32px, 5vw, 44px)', fontWeight: 700,
              color: C.text, margin: 0,
            }}>RSends API</h1>
          </div>
          <p style={{
            fontFamily: C.D, fontSize: 'clamp(20px, 3vw, 28px)', fontWeight: 600,
            margin: '0 0 12px',
            color: '#C8512C',
          }}>Integrate payments in minutes</p>
          <p style={{
            fontFamily: C.S, fontSize: 16, color: C.sub, margin: '0 0 36px',
            maxWidth: 560, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6,
          }}>
            RESTful API with typed webhooks, HMAC verification, and multi-chain support.
            One integration covers EVM, Tron, and Solana.
          </p>
          <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button style={{
              fontFamily: C.D, fontSize: 15, fontWeight: 600, cursor: 'pointer',
              padding: '13px 30px', borderRadius: 12, border: 'none',
              background: C.blue, color: '#fff', transition: 'all 0.2s',
              boxShadow: '0 4px 24px rgba(59,130,246,0.25)',
            }} onClick={onGoToCommand}>Get API Key →</button>
            <button onClick={() => window.open('https://github.com/Emicatte', '_blank')} style={{
              fontFamily: C.D, fontSize: 15, fontWeight: 600, cursor: 'pointer',
              padding: '13px 30px', borderRadius: 12,
              border: `1.5px solid ${C.border}`, background: 'transparent',
              color: C.sub, transition: 'all 0.2s',
            }}>View on GitHub</button>
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* How it works */}
        <motion.div {...fadeUp}>
          <SLabel>HOW IT WORKS</SLabel>
          <STitle>From intent to settlement in 4 steps</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
            gap: isMobile ? 24 : 40,
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {steps.map(s => (
                <div key={s.num} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                  <div style={{
                    fontFamily: C.M, fontSize: 32, fontWeight: 700,
                    color: C.blue, opacity: 0.25, lineHeight: 1, flexShrink: 0, width: 44,
                    textAlign: 'right',
                  }}>{s.num}</div>
                  <div>
                    <div style={{ fontFamily: C.D, fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 6 }}>{s.title}</div>
                    <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{s.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            {!isMobile && (
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <pre style={{ ...codeBlockStyle, width: '100%' }}>
                  <Cmt>{'// Quick start — create an intent\n\n'}</Cmt>
                  <Kw>POST</Kw>{' '}<Punc>/api/v1/merchant/payment-intent</Punc>{'\n\n'}
                  <Punc>{'{\n'}</Punc>
                  {'  '}<Kw>{'"amount"'}</Kw><Punc>{': '}</Punc><Str>{'"100.00"'}</Str><Punc>{',\n'}</Punc>
                  {'  '}<Kw>{'"currency"'}</Kw><Punc>{': '}</Punc><Str>{'"USDC"'}</Str><Punc>{',\n'}</Punc>
                  {'  '}<Kw>{'"chain"'}</Kw><Punc>{': '}</Punc><Str>{'"base"'}</Str><Punc>{',\n'}</Punc>
                  {'  '}<Kw>{'"webhook_url"'}</Kw><Punc>{': '}</Punc><Str>{'"https://your-app.com/hook"'}</Str>{'\n'}
                  <Punc>{'}\n\n'}</Punc>
                  <Cmt>{'// Response\n'}</Cmt>
                  <Punc>{'{\n'}</Punc>
                  {'  '}<Kw>{'"id"'}</Kw><Punc>{': '}</Punc><Str>{'"pi_abc123"'}</Str><Punc>{',\n'}</Punc>
                  {'  '}<Kw>{'"address"'}</Kw><Punc>{': '}</Punc><Str>{'"0x7f2c…e91a"'}</Str>{'\n'}
                  <Punc>{'}'}</Punc>
                </pre>
              </div>
            )}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* API Features */}
        <motion.div {...fadeUp}>
          <SLabel>API FEATURES</SLabel>
          <STitle>Everything you need to build</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)',
            gap: 20,
          }}>
            {features.map(f => (
              <HoverCard key={f.title}>
                <div style={{ marginBottom: 14 }}>{f.icon}</div>
                <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 600, color: C.text, marginBottom: 8 }}>{f.title}</div>
                <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{f.desc}</div>
              </HoverCard>
            ))}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Code Examples */}
        <motion.div {...fadeUp}>
          <SLabel>CODE EXAMPLES</SLabel>
          <STitle>Quick start</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1.2fr',
            gap: 32,
            marginBottom: 40,
          }}>
            <div>
              <h3 style={{ fontFamily: C.D, fontSize: 20, fontWeight: 600, color: C.text, margin: '0 0 12px' }}>Create Payment Intent</h3>
              <p style={{ fontFamily: C.S, fontSize: 15, color: C.sub, lineHeight: 1.6, margin: 0 }}>
                Send a POST request with amount, currency, chain, and webhook URL.
                RSends returns an intent ID and a deposit address. The customer sends crypto
                to that address — RSends handles the rest.
              </p>
            </div>
            <pre style={codeBlockStyle}>
              <Cmt>{'// Create a payment intent\n'}</Cmt>
              <Kw>POST</Kw>{' '}<Punc>/api/v1/merchant/payment-intent</Punc>{'\n\n'}
              <Punc>{'{\n'}</Punc>
              {'  '}<Kw>{'"amount"'}</Kw><Punc>{': '}</Punc><Str>{'"100.00"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"currency"'}</Kw><Punc>{': '}</Punc><Str>{'"USDC"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"chain"'}</Kw><Punc>{': '}</Punc><Str>{'"base"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"webhook_url"'}</Kw><Punc>{': '}</Punc><Str>{'"https://your-app.com/webhook"'}</Str>{'\n'}
              <Punc>{'}'}</Punc>
            </pre>
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1.2fr',
            gap: 32,
          }}>
            <div>
              <h3 style={{ fontFamily: C.D, fontSize: 20, fontWeight: 600, color: C.text, margin: '0 0 12px' }}>Webhook Payload</h3>
              <p style={{ fontFamily: C.S, fontSize: 15, color: C.sub, lineHeight: 1.6, margin: 0 }}>
                When a payment completes, your webhook endpoint receives a typed,
                HMAC-verified event. Every state change fires an event — payment
                matched, screened, split, and settled.
              </p>
            </div>
            <pre style={codeBlockStyle}>
              <Cmt>{'// Webhook event\n'}</Cmt>
              <Punc>{'{\n'}</Punc>
              {'  '}<Kw>{'"event"'}</Kw><Punc>{': '}</Punc><Str>{'"payment.completed"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"intent_id"'}</Kw><Punc>{': '}</Punc><Str>{'"pi_abc123"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"amount"'}</Kw><Punc>{': '}</Punc><Str>{'"100.00"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"currency"'}</Kw><Punc>{': '}</Punc><Str>{'"USDC"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"chain"'}</Kw><Punc>{': '}</Punc><Str>{'"base"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"tx_hash"'}</Kw><Punc>{': '}</Punc><Str>{'"0xabcd…ef01"'}</Str><Punc>{',\n'}</Punc>
              {'  '}<Kw>{'"splits"'}</Kw><Punc>{': ['}</Punc>{'\n'}
              {'    '}<Punc>{'{ '}</Punc><Kw>{'"to"'}</Kw><Punc>{': '}</Punc><Str>{'"0x…"'}</Str><Punc>{', '}</Punc><Kw>{'"bps"'}</Kw><Punc>{': '}</Punc><Str>{'7000'}</Str><Punc>{' },\n'}</Punc>
              {'    '}<Punc>{'{ '}</Punc><Kw>{'"to"'}</Kw><Punc>{': '}</Punc><Str>{'"0x…"'}</Str><Punc>{', '}</Punc><Kw>{'"bps"'}</Kw><Punc>{': '}</Punc><Str>{'3000'}</Str><Punc>{' }\n'}</Punc>
              {'  '}<Punc>{']\n'}</Punc>
              <Punc>{'}'}</Punc>
            </pre>
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Trust / Infrastructure */}
        <motion.div {...fadeUp}>
          <SLabel>INFRASTRUCTURE</SLabel>
          <STitle>Built for scale</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)',
            gap: 20,
          }}>
            {trustItems.map(t => (
              <div key={t.label} style={{
                padding: '32px 20px', textAlign: 'center',
                border: `1px solid ${C.border}`, borderRadius: 16,
                background: 'rgba(10,10,10,0.3)',
              }}>
                <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>{t.icon}</div>
                <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text, lineHeight: 1.4 }}>{t.label}</div>
              </div>
            ))}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Final CTA */}
        <motion.div {...fadeUp} style={{ textAlign: 'center', padding: '20px 0' }}>
          <h2 style={{
            fontFamily: C.D, fontSize: 'clamp(26px, 4vw, 36px)', fontWeight: 700,
            margin: '0 0 14px',
            color: '#C8512C',
          }}>Start building with RSends</h2>
          <p style={{
            fontFamily: C.S, fontSize: 16, color: C.sub, margin: '0 0 32px', lineHeight: 1.6,
          }}>One API. Every chain. Splits, AML, webhooks — built in.</p>
          <button style={{
            fontFamily: C.D, fontSize: 16, fontWeight: 600, cursor: 'pointer',
            padding: '14px 36px', borderRadius: 12, border: 'none',
            background: C.blue, color: '#fff', transition: 'all 0.2s',
            boxShadow: '0 4px 24px rgba(59,130,246,0.25)',
          }} onClick={onGoToCommand}>Get API Key →</button>
        </motion.div>

      </div>
    </motion.div>
  )
}
