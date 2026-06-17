'use client'

import { motion, useScroll, useTransform, useReducedMotion } from 'framer-motion'
import { useRef, ReactNode } from 'react'

export default function Parallax({
  children,
  strength = 30,
  className,
  style,
}: {
  children: ReactNode
  strength?: number
  className?: string
  style?: React.CSSProperties
}) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  })
  const y = useTransform(scrollYProgress, [0, 1], [strength, -strength])

  return (
    <motion.div ref={ref} className={className} style={{ ...style, y: reduced ? 0 : y }}>
      {children}
    </motion.div>
  )
}
