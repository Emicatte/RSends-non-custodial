'use client'

import { motion, useReducedMotion } from 'framer-motion'

type Props = {
  text: string
  className?: string
  style?: React.CSSProperties
  delay?: number
  stagger?: number
}

const EASE = [0.22, 1, 0.36, 1] as const

export default function SplitText({ text, className, style, delay = 0, stagger = 0.04 }: Props) {
  const reduced = useReducedMotion()
  const words = text.split(' ')

  if (reduced) return <span className={className} style={style}>{text}</span>

  return (
    <span className={className} style={{ display: 'inline-block', ...style }}>
      {words.map((word, wi) => (
        <span
          key={wi}
          style={{ display: 'inline-block', overflow: 'hidden', marginRight: '0.25em' }}
        >
          <motion.span
            style={{ display: 'inline-block' }}
            initial={{ y: '110%' }}
            animate={{ y: 0 }}
            transition={{
              duration: 0.9,
              delay: delay + wi * stagger,
              ease: EASE,
            }}
          >
            {word}
          </motion.span>
        </span>
      ))}
    </span>
  )
}
