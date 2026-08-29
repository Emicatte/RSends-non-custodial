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
  description: 'Get paid in stablecoin, straight to your own wallet. A non-custodial B2B payment gateway priced as a monthly subscription, not a percentage of your sales. USDC, USDT and EURC on Base and Ethereum.',
  keywords:    ['non-custodial', 'stablecoin', 'payment gateway', 'USDC', 'USDT', 'EURC', 'Base', 'Ethereum', 'B2B', 'subscription'],
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
  // Matches --rs-paper so iOS Safari tints the status bar to the page
  // background. Metadata is serialised before CSS resolves, so this one has
  // to stay a literal — keep it in step with --rs-paper in globals.css.
  themeColor: '#EFEEEA',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={dmMono.variable}>
      <head>
        {/* Shave the round-trip off the swap window; the CSS and the woff2 come
            from two different hosts. */}
        <link rel="preconnect" href="https://api.fontshare.com" />
        <link rel="preconnect" href="https://cdn.fontshare.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap"
        />
        {/* Home-page entrance gate. Runs before first paint, because the
            alternative — adding the class in an effect — would render the hero
            visible, then hide it, then fade it back in.

            Adds .rs-intro only on a locale home, and only once per session. No
            JavaScript, a repeat view, or prefers-reduced-motion therefore all
            land on the same place: the finished state, painted immediately,
            with no animation defined at all. Nothing here can hide content —
            without the class the entrance rules in globals.css do not exist. */}
        <script
          dangerouslySetInnerHTML={{
            // Deliberately regex-free. This string passes through a TS literal
            // and then React's serializer; an escaped slash does not reliably
            // survive that, and a broken inline script throws on every page.
            // Plain string comparisons cannot be mangled.
            __html: [
              '(function(){try{',
              'var p=location.pathname;',
              "if(p.length>1&&p.charAt(p.length-1)==='/')p=p.slice(0,-1);",
              "if(p!==''&&p!=='/en'&&p!=='/it'&&p!=='/es'&&p!=='/fr'&&p!=='/de')return;",
              "if(sessionStorage.getItem('rs-intro-seen'))return;",
              "sessionStorage.setItem('rs-intro-seen','1');",
              "document.documentElement.classList.add('rs-intro');",
              '}catch(e){}})()',
            ].join(''),
          }}
        />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
      </head>
      {/* Background comes from the `body` rule in globals.css (var(--rs-paper));
          repeating it inline only created a second place to forget. */}
      <body
        className="overflow-x-hidden"
        style={{ minHeight: '100dvh' }}
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