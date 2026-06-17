'use client'

import { motion, useMotionValue, useSpring, useReducedMotion } from 'framer-motion'
import { MouseEvent, ReactNode, useRef } from 'react'

type Props = {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
  strength?: number
  onClick?: () => void
}

export default function MagneticButton({ children, className, style, strength = 0.3, onClick }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const sx = useSpring(x, { stiffness: 200, damping: 20, mass: 0.5 })
  const sy = useSpring(y, { stiffness: 200, damping: 20, mass: 0.5 })

  const handleMove = (e: MouseEvent<HTMLDivElement>) => {
    if (reduced) return
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    x.set((e.clientX - cx) * strength)
    y.set((e.clientY - cy) * strength)
  }
  const handleLeave = () => {
    x.set(0)
    y.set(0)
  }

  return (
    <motion.div
      ref={ref}
      className={className}
      style={{ ...style, x: sx, y: sy, display: 'inline-block' }}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      onClick={onClick}
    >
      {children}
    </motion.div>
  )
}
