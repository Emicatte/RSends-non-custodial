'use client'

import { useEffect } from 'react'

interface ShortcutConfig {
  onEscape?: () => void
  onSearch?: () => void
  enabled?: boolean
}

export function useKeyboardShortcuts({ onEscape, onSearch, enabled = true }: ShortcutConfig) {
  useEffect(() => {
    if (!enabled) return

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onEscape) {
        e.preventDefault()
        onEscape()
      }

      if (e.key === 'k' && (e.metaKey || e.ctrlKey) && onSearch) {
        e.preventDefault()
        onSearch()
      }

      // Block Enter on amount fields to prevent accidental submission
      if (e.key === 'Enter' && (e.target as HTMLElement)?.getAttribute('inputmode') === 'decimal') {
        e.preventDefault()
      }
    }

    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onEscape, onSearch, enabled])
}
