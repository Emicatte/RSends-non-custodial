'use client'

import { motion, useReducedMotion } from 'framer-motion'
import type { Variants } from 'framer-motion'
import { ReactNode } from 'react'

const EASE = [0.22, 1, 0.36, 1] as const

export function StaggerContainer({
  children,
  className,
  style,
  staggerDelay = 0.08,
  once = false,
}: {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
  staggerDelay?: number
  once?: boolean
}) {
  const variants: Variants = {
    hidden: {},
    visible: { transition: { staggerChildren: staggerDelay, delayChildren: 0.1 } },
  }
  return (
    <motion.div
      className={className}
      style={style}
      initial="hidden"
      whileInView="visible"
      viewport={{ once, amount: 0.2 }}
      variants={variants}
    >
      {children}
    </motion.div>
  )
}

export function StaggerItem({
  children,
  className,
  style,
  y = 20,
}: {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
  y?: number
}) {
  const reduced = useReducedMotion()
  const variants: Variants = {
    hidden: { opacity: 0, y: reduced ? 0 : y, transition: { duration: 0.4, ease: EASE } },
    visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
  }
  return (
    <motion.div className={className} style={style} variants={variants}>
      {children}
    </motion.div>
  )
}
