'use client'

import { useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { useUserContacts } from '@/hooks/useUserContacts'

interface ContactRecordedEvent {
  address: string
  label: string
  lastUsed: string
  txCount: number
}

export function ContactsPersistence() {
  const { status } = useSession()
  const { upsert } = useUserContacts()

  const statusRef = useRef(status)
  const upsertRef = useRef(upsert)

  useEffect(() => {
    statusRef.current = status
  }, [status])
  useEffect(() => {
    upsertRef.current = upsert
  }, [upsert])

  useEffect(() => {
    const onRecorded = (e: Event) => {
      const detail = (e as CustomEvent<ContactRecordedEvent>).detail
      if (!detail?.address) return
      if (statusRef.current !== 'authenticated') return
      void upsertRef.current({
        address: detail.address,
        label: detail.label ?? '',
        last_used_at: detail.lastUsed || undefined,
        tx_count: detail.txCount ?? 0,
      })
    }
    window.addEventListener('rsends:contact-recorded', onRecorded)
    return () => {
      window.removeEventListener('rsends:contact-recorded', onRecorded)
    }
  }, [])

  return null
}
