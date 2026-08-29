import type { Metadata, Viewport } from 'next'
import { DM_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import { AuthSessionProvider } from '@/components/auth/AuthSessionProvider'

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
        <link
          rel="stylesheet"
          href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap"
        />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
      </head>
      <body
        className="overflow-x-hidden"
        style={{ background: '#FAFAFA', minHeight: '100dvh' }}
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