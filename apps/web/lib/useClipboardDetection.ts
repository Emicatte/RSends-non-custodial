'use client'

import { useState, useEffect, useCallback } from 'react'

export function useClipboardDetection() {
  const [clipboardAddress, setClipboardAddress] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)

  const checkClipboard = useCallback(async () => {
    if (dismissed) return
    try {
      if (!navigator.clipboard?.readText) return

      const text = await navigator.clipboard.readText()
      const trimmed = text.trim()

      if (/^0x[a-fA-F0-9]{40}$/.test(trimmed)) {
        setClipboardAddress(trimmed)
      } else {
        setClipboardAddress(null)
      }
    } catch {
      // Permission denied or unsupported — silent
    }
  }, [dismissed])

  useEffect(() => {
    window.addEventListener('focus', checkClipboard)
    return () => window.removeEventListener('focus', checkClipboard)
  }, [checkClipboard])

  const dismiss = useCallback(() => {
    setDismissed(true)
    setClipboardAddress(null)
  }, [])

  const reset = useCallback(() => {
    setDismissed(false)
  }, [])

  return { clipboardAddress, dismiss, reset }
}
