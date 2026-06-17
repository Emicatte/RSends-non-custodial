'use client'

import { useState } from 'react'

type Props = {
  /** Optional label shown in the header bar (e.g. "POST /api/v1/tx/callback" or "bash"). */
  label?: string
  /** The code/text to render and copy. */
  code: string
}

/**
 * Reusable dark code block with a copy button.
 * Mono font, ink background, no external deps, no storage APIs.
 */
export function CodeBlock({ label, code }: Props) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  return (
    <div className="my-5 overflow-hidden rounded-xl border border-ink/10 bg-ink">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-2.5">
        <span className="font-mono text-[11px] uppercase tracking-wider text-white/45">
          {label ?? 'code'}
        </span>
        <button
          type="button"
          onClick={copy}
          aria-label="Copy code"
          className="font-mono text-[11px] font-medium text-white/55 transition-colors hover:text-terracotta"
        >
          {copied ? 'Copied ✓' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-4">
        <code className="font-mono text-[12.5px] leading-relaxed text-white/85 whitespace-pre">
          {code}
        </code>
      </pre>
    </div>
  )
}
