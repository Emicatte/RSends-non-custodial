'use client'

import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'

export default function AppNav() {
  return (
    <>
      {/* Top accent bar — overlays the nav's top edge (z 1001 > nav's 1000),
          so the nav's h-14/h-16 is the full height of the fixed chrome. */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: C.text,
          zIndex: 1001,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: 96,
            height: 3,
            background: C.purple,
          }}
        />
      </div>

      {/* Navbar — brand only. Non-custodial dashboard: the merchant operates
          with a session; no wallet connect, no chain switcher. */}
      <nav
        className="fixed top-0 left-0 right-0 z-[1000] flex h-14 md:h-16 items-center justify-between gap-4 bg-white/85 border-b border-black/[0.06] backdrop-blur-md px-5 md:px-6"
        style={{
          WebkitBackdropFilter: 'blur(16px) saturate(180%)',
        }}
      >
        <Link href="/" className="rp-brand flex items-center gap-2 no-underline">
          <img
            src="/favicon.svg"
            alt="RSends"
            width={28}
            height={28}
            className="rp-brand-dot rounded-[7px]"
          />
          <span
            className="hidden md:inline font-display text-[16px] font-extrabold tracking-[-0.03em]"
            style={{ color: C.text }}
          >
            RSends
          </span>
        </Link>
      </nav>
    </>
  )
}
