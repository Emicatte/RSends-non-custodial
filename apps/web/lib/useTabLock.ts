/**
 * useTabLock — BroadcastChannel per mutual exclusion tra tab.
 *
 * Quando una TX è in corso in una tab:
 * - Le altre tab mostrano "Transazione in corso su un'altra scheda"
 * - Non possono inviare fino a quando la prima tab completa
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const CHANNEL_NAME = 'rsend_tx_lock'

export function useTabLock() {
  const [isLocked, setIsLocked] = useState(false)
  const [lockedBy, setLockedBy] = useState<string | null>(null)
  const channelRef = useRef<BroadcastChannel | null>(null)
  const tabId = useRef(Math.random().toString(36).slice(2, 8))

  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return

    const channel = new BroadcastChannel(CHANNEL_NAME)
    channelRef.current = channel

    channel.onmessage = (event) => {
      const { type, sender } = event.data
      if (sender === tabId.current) return // ignora i propri messaggi

      if (type === 'lock') {
        setIsLocked(true)
        setLockedBy(sender)
      } else if (type === 'unlock') {
        setIsLocked(false)
        setLockedBy(null)
      }
    }

    return () => channel.close()
  }, [])

  const acquireLock = useCallback(() => {
    channelRef.current?.postMessage({ type: 'lock', sender: tabId.current })
  }, [])

  const releaseLock = useCallback(() => {
    channelRef.current?.postMessage({ type: 'unlock', sender: tabId.current })
    setIsLocked(false)
    setLockedBy(null)
  }, [])

  return { isLocked, lockedBy, acquireLock, releaseLock, tabId: tabId.current }
}
