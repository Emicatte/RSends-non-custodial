'use client'

import { motion, useReducedMotion } from 'framer-motion'
import type { Variants } from 'framer-motion'
import { ReactNode } from 'react'

type Props = {
  children: ReactNode
  delay?: number
  y?: number
  duration?: number
  className?: string
  style?: React.CSSProperties
  once?: boolean // false = bidirectional (re-animates on every viewport entry/exit)
}

const EASE = [0.22, 1, 0.36, 1] as const

export default function FadeIn({
  children,
  delay = 0,
  y = 24,
  duration = 0.8,
  className,
  style,
  once = false,
}: Props) {
  const reduced = useReducedMotion()

  const variants: Variants = {
    hidden: {
      opacity: 0,
      y: reduced ? 0 : y,
      transition: { duration: reduced ? 0 : duration * 0.6, ease: EASE },
    },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduced ? 0 : duration, delay, ease: EASE },
    },
  }

  return (
    <motion.div
      className={className}
      style={style}
      initial="hidden"
      whileInView="visible"
      viewport={{ once, amount: 0.2, margin: '0px 0px -5% 0px' }}
      variants={variants}
    >
      {children}
    </motion.div>
  )
}
