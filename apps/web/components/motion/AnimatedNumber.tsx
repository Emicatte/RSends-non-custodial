'use client'

import { useEffect, useRef } from 'react'
import { useMotionValue, useSpring, useReducedMotion } from 'framer-motion'

type Props = {
  value: number
  format: (n: number) => string
  style?: React.CSSProperties
}

export default function AnimatedNumber({ value, format, style }: Props) {
  const reduced = useReducedMotion()
  const mv = useMotionValue(value)
  const spring = useSpring(mv, { stiffness: 80, damping: 22, mass: 0.8 })
  const ref = useRef<HTMLSpanElement>(null)

  // Update motion value when prop changes
  useEffect(() => {
    mv.set(value)
  }, [value, mv])

  // Subscribe to spring changes and update DOM directly (no re-render per frame)
  useEffect(() => {
    if (reduced) return
    const unsubscribe = spring.on('change', (v) => {
      if (ref.current) ref.current.textContent = format(v)
    })
    return unsubscribe
  }, [spring, format, reduced])

  return (
    <span ref={ref} style={style}>
      {format(reduced ? value : spring.get())}
    </span>
  )
}
