'use client'

import { useCallback, useRef, useState, useEffect } from 'react'

export type TransitionPhase = 'idle' | 'exit' | 'swap' | 'enter'
export type SlideDirection = 'left' | 'right'

export function useTabTransition<T extends string>(
  initial: T,
  order: readonly T[]
) {
  const [tab, setTab] = useState<T>(initial)
  const [phase, setPhase] = useState<TransitionPhase>('idle')
  const [direction, setDirection] = useState<SlideDirection>('right')
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const pendingRef = useRef<T | null>(null)

  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
  }

  useEffect(() => () => clearTimers(), [])

  const transitionTo = useCallback((next: T) => {
    if (next === tab) return
    if (phase !== 'idle') {
      pendingRef.current = next
      return
    }
    clearTimers()
    const oldIdx = order.indexOf(tab)
    const newIdx = order.indexOf(next)
    setDirection(newIdx > oldIdx ? 'right' : 'left')
    setPhase('exit')
    pendingRef.current = null

    timersRef.current.push(setTimeout(() => {
      setTab(next)
      setPhase('swap')
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setPhase('enter')
          timersRef.current.push(setTimeout(() => {
            setPhase('idle')
            if (pendingRef.current && pendingRef.current !== next) {
              const queued = pendingRef.current
              pendingRef.current = null
              transitionTo(queued)
            }
          }, 500))
        })
      })
    }, 200))
  }, [tab, phase, order])

  return { tab, phase, direction, transitionTo }
}
