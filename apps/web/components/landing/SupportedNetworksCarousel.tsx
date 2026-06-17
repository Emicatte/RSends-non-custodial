'use client'

import Image from 'next/image'
import { useCallback, useRef, useState } from 'react'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'

type Chain = {
  slug: string
  name: string
  color: string
  svg?: string
}

const CHAINS: Chain[] = [
  { slug: 'base',      name: 'Base',      color: '#0052FF', svg: '/chains/base.svg' },
  { slug: 'ethereum',  name: 'Ethereum',  color: '#627EEA', svg: '/chains/ethereum.svg' },
  { slug: 'arbitrum',  name: 'Arbitrum',  color: '#28A0F0', svg: '/chains/arbitrum.svg' },
  { slug: 'optimism',  name: 'Optimism',  color: '#FF0420', svg: '/chains/optimism.svg' },
  { slug: 'polygon',   name: 'Polygon',   color: '#8247E5', svg: '/chains/polygon.svg' },
  { slug: 'bnb',       name: 'BNB Chain', color: '#F3BA2F', svg: '/chains/bnb.svg' },
  { slug: 'avalanche', name: 'Avalanche', color: '#E84142', svg: '/chains/avalanche.svg' },
  { slug: 'tron',      name: 'Tron',      color: '#EB0029', svg: '/chains/tron.svg' },
  { slug: 'solana',    name: 'Solana',    color: '#9945FF', svg: '/chains/solana.svg' },
]

const LOGOS: Chain[] = [...CHAINS, ...CHAINS]

function LetterBubble({ letter, color }: { letter: string; color: string }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 44,
        height: 44,
        borderRadius: '50%',
        background: color,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
        fontFamily: C.D,
        fontWeight: 600,
        fontSize: 20,
        lineHeight: 1,
      }}
    >
      {letter}
    </div>
  )
}

export default function SupportedNetworksCarousel() {
  const itemRefs = useRef<Array<HTMLAnchorElement | null>>([])
  const [hovering, setHovering] = useState(false)
  const [focusedIdx, setFocusedIdx] = useState<number | null>(null)

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const mouseX = e.clientX
    let nearestIdx = -1
    let nearestDist = Infinity
    itemRefs.current.forEach((el, i) => {
      if (!el) return
      const r = el.getBoundingClientRect()
      if (r.width === 0) return
      const centerX = r.left + r.width / 2
      const d = Math.abs(centerX - mouseX)
      if (d < nearestDist) {
        nearestDist = d
        nearestIdx = i
      }
    })
    setFocusedIdx(nearestIdx >= 0 ? nearestIdx : null)
  }, [])

  const handleMouseEnter = useCallback(() => setHovering(true), [])
  const handleMouseLeave = useCallback(() => {
    setHovering(false)
    setFocusedIdx(null)
  }, [])

  return (
    <section
      style={{
        width: '100%',
        padding: 'clamp(16px, 2vw, 24px) 0',
      }}
    >
      <div
        className="snc-viewport"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onMouseMove={handleMouseMove}
        data-paused={hovering ? 'true' : 'false'}
        style={{
          overflow: 'hidden',
          position: 'relative',
          WebkitMaskImage:
            'linear-gradient(to right, transparent 0, black 80px, black calc(100% - 80px), transparent 100%)',
          maskImage:
            'linear-gradient(to right, transparent 0, black 80px, black calc(100% - 80px), transparent 100%)',
        }}
      >
        <div className="snc-track">
          {LOGOS.map((chain, i) => {
            const isFocused = hovering && focusedIdx === i
            const isDimmed = hovering && focusedIdx !== null && focusedIdx !== i
            return (
              <Link
                href={`/markets?chain=${chain.slug}`}
                key={`${chain.slug}-${i}`}
                ref={(el: HTMLAnchorElement | null) => {
                  itemRefs.current[i] = el
                }}
                aria-label={`View ${chain.name} markets`}
                className="snc-item"
                data-focused={isFocused ? 'true' : undefined}
                data-dimmed={isDimmed ? 'true' : undefined}
              >
                {chain.svg ? (
                  <Image
                    src={chain.svg}
                    alt={chain.name}
                    width={44}
                    height={44}
                    style={{ display: 'block' }}
                    priority={i < 3}
                  />
                ) : (
                  <LetterBubble letter={chain.name[0]!} color={chain.color} />
                )}
              </Link>
            )
          })}
        </div>
      </div>

      <style>{`
        @keyframes snc-scroll {
          from { transform: translateX(0); }
          to   { transform: translateX(-50%); }
        }
        .snc-track {
          display: flex;
          gap: clamp(40px, 5vw, 72px);
          width: max-content;
          animation: snc-scroll 35s linear infinite;
          will-change: transform;
        }
        .snc-viewport[data-paused="true"] .snc-track {
          animation-play-state: paused;
        }
        .snc-item {
          flex: 0 0 auto;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 44px;
          height: 44px;
          filter: grayscale(1);
          opacity: 0.7;
          transform: scale(1);
          transition:
            filter 220ms ease,
            opacity 220ms ease,
            transform 220ms ease;
          cursor: pointer;
          border-radius: 50%;
          outline: none;
        }
        @media (hover: hover) and (pointer: fine) {
          .snc-item[data-focused="true"] {
            filter: grayscale(0);
            opacity: 1;
            transform: scale(1.1);
          }
          .snc-item[data-dimmed="true"] {
            filter: grayscale(1) blur(2.5px);
            opacity: 0.35;
          }
        }
        .snc-item:focus-visible {
          outline: 2px solid ${C.purple};
          outline-offset: 4px;
        }
        @media (prefers-reduced-motion: reduce) {
          .snc-track { animation: none; }
        }
      `}</style>
    </section>
  )
}
