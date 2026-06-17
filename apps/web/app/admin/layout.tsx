'use client'

import { useEffect } from 'react'

/**
 * Admin layout — completely isolates admin pages from:
 * - RainbowKit/WalletConnect global CSS
 * - RPagos animated background orbs
 * - Any global overlay styles
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // Hide any RainbowKit / global background elements that bleed through
    document.body.classList.add('admin-mode')
    return () => { document.body.classList.remove('admin-mode') }
  }, [])

  return (
    <div id="admin-root" className="admin-isolation">
      {children}
    </div>
  )
}
