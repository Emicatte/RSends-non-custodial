import type { Metadata, Viewport } from 'next'
import { DM_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import { AuthSessionProvider } from '@/components/auth/AuthSessionProvider'
import { HYDRATION_RECOVERY_SCRIPT } from '@/lib/hydrationRecovery'

const dmMono = DM_Mono({
  subsets:  ['latin'],
  variable: '--font-mono',
  display:  'swap',
  weight:   ['400', '500'],
})

export const metadata: Metadata = {
  title:       'RSends — Non-custodial stablecoin payment gateway',
  description: 'Get paid in stablecoin, straight to your own wallet. A non-custodial B2B payment gateway priced as a monthly subscription, not a percentage of your sales. USDC and USDT on Base and Ethereum.',
  keywords:    ['non-custodial', 'stablecoin', 'payment gateway', 'USDC', 'USDT', 'Base', 'Ethereum', 'B2B', 'subscription'],
  icons: {
    icon: [
      
      { url: '/favicon.svg', type: 'image/svg+xml' },
    ],
    apple: '/apple-touch-icon.png',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  // Dark theme: prevents iOS Safari from rendering the status bar
  // in light mode when the app background is dark.
  themeColor: '#FAFAFA',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={dmMono.variable}>
      <head>
        {/* Blank-screen recovery. Must be the first script in the document: a wedged React
            root (#329, uncatchable by any error boundary — see lib/hydrationRecovery.ts)
            leaves the server HTML on screen forever, and on /pay that HTML is an empty
            <body>. This installs a plain-DOM fallback before the failure can happen.

            CSP: this is an inline script, allowed today by `script-src 'self' 'unsafe-inline'`
            (next.config.mjs:121, confirmed on the deployed response). next.config.mjs:114-118
            tracks moving to `'nonce-…' 'strict-dynamic'` — at that point this script DIES
            SILENTLY unless it is given the per-request nonce. Whoever does that migration has
            to carry this tag with it; nothing will fail loudly if they don't. */}
        <script dangerouslySetInnerHTML={{ __html: HYDRATION_RECOVERY_SCRIPT }} />
        <link
          rel="stylesheet"
          href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap"
        />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
      </head>
      <body
        className="overflow-x-hidden"
        style={{ background: 'var(--rs-paper)', minHeight: '100dvh' }}
      >
        <AuthSessionProvider>
          <Providers>
            {children}
          </Providers>
        </AuthSessionProvider>
      </body>
    </html>
  )
}