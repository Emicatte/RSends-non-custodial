'use client'

import { useState, useRef, useEffect } from 'react'
import { motion, useInView } from 'framer-motion'
import { C } from '@/app/designTokens'

const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

const CONTRACT = '0x81d78BDD917D5A43a9E424B905407495b8f2c0f4'

// ── Syntax highlighting (inline, simple) ──
function Code({ children, lang }: { children: string; lang?: string }) {
  // Simple keyword highlighting
  const highlight = (code: string) => {
    const lines = code.split('\n')
    return lines.map((line, i) => {
      let colored = line
        // Keywords
        .replace(/\b(function|const|let|var|return|async|await|import|from|export|interface|type|public|external|payable|view|returns|mapping|address|uint256|bool|string|memory|calldata|emit|require|event|struct)\b/g, '<kw>$1</kw>')
        // Strings
        .replace(/(["'`])(?:(?!\1).)*\1/g, '<str>$&</str>')
        // Comments
        .replace(/(\/\/.*)$/g, '<cmt>$1</cmt>')
        // Numbers
        .replace(/\b(\d+\.?\d*)\b/g, '<num>$1</num>')
        // Function names
        .replace(/\b([a-zA-Z_]\w*)\s*\(/g, '<fn>$1</fn>(')

      return (
        <div key={i} style={{ display: 'flex', minHeight: 20 }}>
          <span style={{ width: 28, color: C.dim, fontSize: 10, userSelect: 'none', textAlign: 'right', paddingRight: 12, flexShrink: 0 }}>{i + 1}</span>
          <span
            dangerouslySetInnerHTML={{ __html: colored
              .replace(/<kw>/g, '<span style="color:#c084fc">')
              .replace(/<\/kw>/g, '</span>')
              .replace(/<str>/g, '<span style="color:#86efac">')
              .replace(/<\/str>/g, '</span>')
              .replace(/<cmt>/g, '<span style="color:rgba(10,10,10,0.55)">')
              .replace(/<\/cmt>/g, '</span>')
              .replace(/<num>/g, '<span style="color:#FFB547">')
              .replace(/<\/num>/g, '</span>')
              .replace(/<fn>/g, '<span style="color:#C8512C">')
              .replace(/<\/fn>/g, '</span>')
            }}
          />
        </div>
      )
    })
  }

  return (
    <div style={{
      background: '#FAFAFA', borderRadius: 12, padding: '14px 16px',
      border: `1px solid ${C.border}`, fontFamily: C.M, fontSize: 11,
      color: C.text, overflow: 'auto', lineHeight: 1.6,
    }}>
      {lang && (
        <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>
          {lang}
        </div>
      )}
      {highlight(children)}
    </div>
  )
}

// ── Copy button ──
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <motion.button
      whileTap={{ scale: 0.92 }}
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      style={{
        padding: '5px 10px', borderRadius: 8, border: `1px solid ${C.border}`,
        background: copied ? `${C.green}15` : 'rgba(10,10,10,0.04)',
        color: copied ? C.green : C.sub, fontFamily: C.M, fontSize: 10,
        cursor: 'pointer', transition: 'all 0.2s', display: 'flex', alignItems: 'center', gap: 4,
      }}
    >
      {copied ? '✓ Copied' : '⎘ Copy'}
    </motion.button>
  )
}

// ── Tech stack badge ──
function TechBadge({ label }: { label: string }) {
  return (
    <motion.span
      whileHover={{
        boxShadow: '0 0 16px rgba(59,130,246,0.2)',
        borderColor: 'rgba(59,130,246,0.3)',
      }}
      style={{
        padding: '5px 12px', borderRadius: 8,
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${C.border}`,
        fontFamily: C.M, fontSize: 10, color: C.sub,
        transition: 'all 0.25s ease', cursor: 'default',
      }}
    >
      {label}
    </motion.span>
  )
}

export default function DevelopersOverlay() {
  const [expandedEndpoint, setExpandedEndpoint] = useState<number | null>(null)
  const [codeTab, setCodeTab] = useState<Record<number, 'ts' | 'curl'>>({})

  const endpoints = [
    {
      method: 'POST',
      path: '/api/v1/tx/callback',
      desc: 'Transaction completion webhook',
      example: {
        request: `{
  "tx_hash": "0xabc...def",
  "fiscal_ref": "RSN-2026-00847",
  "status": "completed"
}`,
        response: `{
  "acknowledged": true
}`,
      },
    },
    {
      method: 'GET',
      path: '/api/v1/tx/{fiscal_ref}',
      desc: 'Retrieve transaction by fiscal reference',
      example: {
        request: 'GET /api/v1/tx/RSN-2026-00847',
        response: `{
  "fiscal_ref": "RSN-2026-00847",
  "amount": "1000.00",
  "token": "USDC",
  "status": "completed",
  "compliance": "verified"
}`,
      },
    },
    {
      method: 'GET',
      path: '/api/v1/forwarding/rules',
      desc: 'List active forwarding rules',
      example: {
        request: 'GET /api/v1/forwarding/rules?wallet=0xB217...691D',
        response: `{
  "rules": [{
    "destination": "0x...",
    "split_percent": 70,
    "threshold": "0.001",
    "active": true
  }]
}`,
      },
    },
    {
      method: 'POST',
      path: '/api/v1/forwarding/rules',
      desc: 'Create or update a forwarding rule',
      example: {
        request: `{
  "source_wallet": "0x...",
  "destination_wallet": "0x...",
  "min_threshold": 0.001,
  "split_enabled": true,
  "split_percent": 70
}`,
        response: `{
  "id": 42,
  "status": "active",
  "created_at": "2026-03-28T10:00:00Z"
}`,
      },
    },
    {
      method: 'GET',
      path: '/api/v1/forwarding/logs',
      desc: 'Transaction forwarding activity logs',
      example: {
        request: 'GET /api/v1/forwarding/logs?wallet=0x...&limit=10',
        response: `{
  "logs": [{
    "id": 1,
    "amount": 1.5,
    "token": "ETH",
    "status": "completed",
    "tx_hash": "0x..."
  }]
}`,
      },
    },
    {
      method: 'GET',
      path: '/api/v1/health',
      desc: 'System health check endpoint',
      example: {
        request: 'GET /api/v1/health',
        response: `{
  "status": "healthy",
  "oracle": "online",
  "contracts": "verified",
  "uptime": "99.98%"
}`,
      },
    },
  ]

  const integrationSteps = [
    {
      n: '01',
      title: 'Connect',
      ts: `import { createConfig, http } from 'wagmi'
import { base } from 'wagmi/chains'

const config = createConfig({
  chains: [base],
  transports: {
    [base.id]: http(),
  },
})`,
      curl: `# Verify contract on Base
curl https://api.basescan.org/api \\
  -d "module=contract" \\
  -d "action=getabi" \\
  -d "address=${CONTRACT}"`,
    },
    {
      n: '02',
      title: 'Request Oracle Signature',
      ts: `const response = await fetch('/api/v1/oracle/sign', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    sender: address,
    recipient: '0x...',
    amount: parseEther('1.0'),
    token: 'ETH',
  }),
})
const { signature, deadline } = await response.json()`,
      curl: `curl -X POST https://api.rsend.io/api/v1/oracle/sign \\
  -H "Content-Type: application/json" \\
  -d '{
    "sender": "0x...",
    "recipient": "0x...",
    "amount": "1000000000000000000",
    "token": "ETH"
  }'`,
    },
    {
      n: '03',
      title: 'Execute Payment',
      ts: `import { writeContract } from 'wagmi/actions'

await writeContract(config, {
  address: '${CONTRACT}',
  abi: FeeRouterV4ABI,
  functionName: 'executePayment',
  args: [recipient, amount, signature, deadline],
  value: amount,
})`,
      curl: `# Execute via cast (Foundry)
cast send ${CONTRACT} \\
  "executePayment(address,uint256,bytes,uint256)" \\
  0xRecipient 1000000000000000000 0xSignature 1711600000 \\
  --value 1ether \\
  --rpc-url https://mainnet.base.org`,
    },
  ]

  const contractFunctions = `// FeeRouterV4.sol — Key Functions
function executePayment(
    address recipient,
    uint256 amount,
    bytes calldata oracleSignature,
    uint256 deadline
) external payable

function setSplitConfig(
    address dest1,
    address dest2,
    uint256 splitBps
) external

function getRouteConfig(
    address sender
) external view returns (RouteConfig memory)

event PaymentExecuted(
    address indexed sender,
    address indexed recipient,
    uint256 amount,
    uint256 fee
)`

  return (
    <div>
      {/* Header */}
      <h2 style={{ fontFamily: C.D, fontSize: 24, fontWeight: 800, color: C.text, marginBottom: 4 }}>
        <span style={GRAD}>Developers</span>
      </h2>
      <p style={{ fontFamily: C.M, fontSize: 12, color: C.dim, marginBottom: 28 }}>
        Build on RSends — smart contracts, APIs, and integration guides
      </p>

      {/* ═══ A) Smart Contract ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Smart Contract
        </div>
        <div style={{
          padding: '16px', borderRadius: 14,
          background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
          marginBottom: 12,
        }}>
          {/* Address + copy */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ fontFamily: C.M, fontSize: 12, color: C.text, wordBreak: 'break-all' }}>
              {CONTRACT}
            </div>
            <CopyButton text={CONTRACT} />
          </div>

          {/* Verified badge */}
          <a
            href={`https://basescan.org/address/${CONTRACT}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 8,
              background: `${C.green}10`, border: `1px solid ${C.green}20`,
              fontFamily: C.M, fontSize: 10, color: C.green,
              textDecoration: 'none', transition: 'all 0.2s',
            }}
          >
            Verified on Basescan ✅
          </a>
        </div>

        {/* Code snippet */}
        <Code lang="solidity">{contractFunctions}</Code>
      </div>

      {/* ═══ B) API Reference ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            API Reference
          </div>
          <span style={{
            padding: '4px 10px', borderRadius: 6,
            background: `${C.blue}10`, border: `1px solid ${C.blue}20`,
            fontFamily: C.M, fontSize: 9, color: C.blue,
          }}>
            Swagger at /docs
          </span>
        </div>

        <div style={{
          borderRadius: 14, overflow: 'hidden',
          border: `1px solid ${C.border}`,
        }}>
          {endpoints.map((ep, i) => {
            const isExpanded = expandedEndpoint === i
            const methodColor = ep.method === 'POST' ? C.amber : C.green
            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.05, duration: 0.3 }}
              >
                <button
                  onClick={() => setExpandedEndpoint(isExpanded ? null : i)}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', background: isExpanded ? 'rgba(10,10,10,0.03)' : 'transparent',
                    border: 'none', borderBottom: `1px solid ${C.border}`,
                    cursor: 'pointer', transition: 'background 0.15s',
                    textAlign: 'left',
                  }}
                  onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = 'rgba(10,10,10,0.02)' }}
                  onMouseLeave={e => { if (!isExpanded) e.currentTarget.style.background = 'transparent' }}
                >
                  <span style={{
                    fontFamily: C.M, fontSize: 9, fontWeight: 700,
                    color: methodColor, padding: '2px 6px', borderRadius: 4,
                    background: `${methodColor}15`, minWidth: 36, textAlign: 'center',
                  }}>
                    {ep.method}
                  </span>
                  <span style={{ fontFamily: C.M, fontSize: 11, color: C.text, flex: 1 }}>{ep.path}</span>
                  <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>{ep.desc}</span>
                  <span style={{ color: C.dim, fontSize: 10, transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>▾</span>
                </button>
                <motion.div
                  initial={false}
                  animate={{ height: isExpanded ? 'auto' : 0, opacity: isExpanded ? 1 : 0 }}
                  transition={{ duration: 0.25 }}
                  style={{ overflow: 'hidden' }}
                >
                  <div style={{ padding: '12px 14px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div>
                      <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Request</div>
                      <div style={{ background: '#FAFAFA', borderRadius: 8, padding: '10px 12px', fontFamily: C.M, fontSize: 10, color: C.sub, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                        {ep.example.request}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Response</div>
                      <div style={{ background: '#FAFAFA', borderRadius: 8, padding: '10px 12px', fontFamily: C.M, fontSize: 10, color: C.green, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                        {ep.example.response}
                      </div>
                    </div>
                  </div>
                </motion.div>
              </motion.div>
            )
          })}
        </div>
      </div>

      {/* ═══ C) Integration in 3 Steps ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Integration in 3 Steps
        </div>
        {integrationSteps.map((step, i) => {
          const tab = codeTab[i] || 'ts'
          return (
            <motion.div
              key={step.n}
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1, duration: 0.4 }}
              style={{ marginBottom: 16 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <span style={{
                  fontFamily: C.M, fontSize: 10, fontWeight: 700,
                  color: C.blue, padding: '3px 8px', borderRadius: 6,
                  background: `${C.blue}10`, border: `1px solid ${C.blue}20`,
                }}>
                  {step.n}
                </span>
                <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text }}>{step.title}</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                  {(['ts', 'curl'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => setCodeTab(prev => ({ ...prev, [i]: t }))}
                      style={{
                        padding: '3px 10px', borderRadius: 6, border: 'none',
                        background: tab === t ? 'rgba(10,10,10,0.08)' : 'transparent',
                        color: tab === t ? C.text : C.dim,
                        fontFamily: C.M, fontSize: 9, cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {t === 'ts' ? 'TypeScript' : 'cURL'}
                    </button>
                  ))}
                </div>
              </div>
              <Code lang={tab === 'ts' ? 'typescript' : 'bash'}>{tab === 'ts' ? step.ts : step.curl}</Code>
            </motion.div>
          )
        })}
      </div>

      {/* ═══ D) Open Source ═══ */}
      <div>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Open Source
        </div>
        <div style={{
          padding: '18px 16px', borderRadius: 14,
          background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            {/* GitHub icon */}
            <svg width="20" height="20" viewBox="0 0 24 24" fill={C.text}>
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
            <a
              href="https://github.com/Emicatte/feerouter-dapp"
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text, textDecoration: 'none' }}
            >
              Emicatte/feerouter-dapp
            </a>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {['Next.js', 'FastAPI', 'Solidity', 'Foundry', 'OpenZeppelin'].map((t, i) => (
              <motion.div
                key={t}
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 }}
              >
                <TechBadge label={t} />
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
