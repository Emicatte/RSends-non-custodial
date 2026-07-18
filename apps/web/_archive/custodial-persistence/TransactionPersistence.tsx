'use client'

import { useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { useUserTransactions } from '@/hooks/useUserTransactions'
import { stashPendingMerge } from '@/components/auth/PostLoginMerge'
import type { TxSubmittedEvent, TxConfirmedEvent } from '@/lib/tx-events'

export function TransactionPersistence() {
  const { status } = useSession()
  const { create, update, transactions } = useUserTransactions()

  const statusRef = useRef(status)
  const createRef = useRef(create)
  const updateRef = useRef(update)
  const txsRef = useRef(transactions)
  const clientIdMapRef = useRef<Map<string, string>>(new Map())
  const pendingConfirmsRef = useRef<Map<string, TxConfirmedEvent>>(new Map())

  useEffect(() => {
    statusRef.current = status
  }, [status])
  useEffect(() => {
    createRef.current = create
  }, [create])
  useEffect(() => {
    updateRef.current = update
  }, [update])
  useEffect(() => {
    txsRef.current = transactions
  }, [transactions])

  useEffect(() => {
    const onSubmitted = (e: Event) => {
      const detail = (e as CustomEvent<TxSubmittedEvent>).detail
      if (!detail) return
      const { clientId, ...payload } = detail
      if (statusRef.current === 'authenticated') {
        void (async () => {
          const created = await createRef.current(payload)
          if (created) {
            clientIdMapRef.current.set(clientId, created.id)
            const queued = pendingConfirmsRef.current.get(clientId)
            if (queued) {
              pendingConfirmsRef.current.delete(clientId)
              const { tx_status, gas_used, gas_price_gwei, block_number, confirmed_at } = queued
              await updateRef.current(created.id, {
                tx_status,
                gas_used,
                gas_price_gwei,
                block_number,
                confirmed_at,
              })
            }
          }
        })()
      } else {
        stashPendingMerge(payload)
      }
    }

    const onConfirmed = (e: Event) => {
      const detail = (e as CustomEvent<TxConfirmedEvent>).detail
      if (!detail) return
      const { clientId, tx_hash, chain_id, tx_status, gas_used, gas_price_gwei, block_number, confirmed_at } = detail

      if (statusRef.current === 'authenticated') {
        let serverId = clientIdMapRef.current.get(clientId)
        if (!serverId) {
          const match = txsRef.current.find(
            (t) => t.tx_hash.toLowerCase() === tx_hash.toLowerCase() && t.chain_id === chain_id,
          )
          if (match) serverId = match.id
        }
        if (serverId) {
          void updateRef.current(serverId, {
            tx_status,
            gas_used,
            gas_price_gwei,
            block_number,
            confirmed_at,
          })
        } else {
          pendingConfirmsRef.current.set(clientId, detail)
        }
      } else {
        stashPendingMerge({
          chain_id,
          tx_hash,
          wallet_address: '',
          tx_type: 'transfer',
          tx_status,
          extra_metadata: {
            _confirmUpdate: true,
            gas_used,
            gas_price_gwei,
            block_number,
            confirmed_at,
          },
        })
      }
    }

    window.addEventListener('rsends:tx-submitted', onSubmitted)
    window.addEventListener('rsends:tx-confirmed', onConfirmed)
    return () => {
      window.removeEventListener('rsends:tx-submitted', onSubmitted)
      window.removeEventListener('rsends:tx-confirmed', onConfirmed)
    }
  }, [])

  return null
}
