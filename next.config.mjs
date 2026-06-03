import withBundleAnalyzer from '@next/bundle-analyzer'
import createNextIntlPlugin from 'next-intl/plugin'

const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

const analyzer = withBundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
})

// TODO: disable Vercel Toolbar for Production via Dashboard
// (Project Settings → Advanced → Vercel Toolbar → toggle off for Production).
// The toolbar script at https://vercel.live/_next-live/feedback/feedback.js is
// blocked by our CSP (intentional) but still generates console warnings.
// No runtime flag exists to suppress it from next.config — must be done in the dashboard.

/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === 'development'
const devConnect = isDev ? ' ws://localhost:* http://localhost:*' : ''

// CORS allowlist: comma-separated origins. In production an empty list
// means "no cross-origin allowed" (safe default). In development we fall
// back to http://localhost:3000 so local dev still works without setup.
const corsAllowedOrigins = (process.env.ALLOWED_ORIGINS || '')
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean)
const corsOrigins =
  corsAllowedOrigins.length > 0
    ? corsAllowedOrigins
    : isDev
      ? ['http://localhost:3000']
      : []
const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const nextConfig = {
  webpack: (config) => {
    config.resolve.fallback = {
      ...config.resolve.fallback,
      '@react-native-async-storage/async-storage': false,
      'pino-pretty': false,
    };
    return config;
  },
  headers: async () => [
    {
      source: '/(.*)',
      headers: [
        {
          key: 'Content-Security-Policy',
          value: [
            "default-src 'self'",
            // L2 (residual): 'unsafe-inline' is still required by Next.js inline
            // hydration scripts. Removing it safely needs a NONCE-based CSP
            // (per-request nonce from middleware injected into Next's scripts +
            // script-src 'nonce-…' 'strict-dynamic'). Tracked as a follow-up;
            // do NOT drop 'unsafe-inline' without that, it breaks the app.
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://api.fontshare.com",
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.fontshare.com",
            "img-src 'self' data: blob: https:",
            `connect-src 'self' https://rpagos-backend.onrender.com wss://rpagos-backend.onrender.com https://*.infura.io https://*.alchemy.com https://*.llamarpc.com https://*.publicnode.com https://rpc.ankr.com https://mainnet.base.org https://sepolia.base.org https://arb1.arbitrum.io https://mainnet.optimism.io https://polygon-rpc.com https://bsc-dataseed.binance.org https://api.avax.network https://mainnet.era.zksync.io https://forno.celo.org https://rpc.blast.io https://api.trongrid.io https://api.shasta.trongrid.io wss://*.walletconnect.com wss://*.walletconnect.org https://*.walletconnect.org https://*.web3modal.org https://api.coingecko.com https://ipapi.co${devConnect}`,
            "frame-src 'self' https://verify.walletconnect.com https://verify.walletconnect.org",
            "worker-src 'self' blob:",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "upgrade-insecure-requests",
          ].join('; '),
        },
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
      ],
    },
    // CORS: one header entry per allowlisted origin, gated by the request's
    // Origin header. Requests from non-allowlisted origins receive no CORS
    // headers → preflight fails → browser blocks the request. Wildcard '*'
    // is intentionally absent: cross-origin access is explicit-only.
    ...corsOrigins.map((origin) => ({
      source: '/api/:path*',
      has: [
        {
          type: 'header',
          key: 'origin',
          value: `^${escapeRegex(origin)}$`,
        },
      ],
      headers: [
        { key: 'Access-Control-Allow-Origin', value: origin },
        { key: 'Vary', value: 'Origin' },
        { key: 'Access-Control-Allow-Methods', value: 'GET, POST, OPTIONS' },
        { key: 'Access-Control-Allow-Headers', value: 'Content-Type, Authorization' },
      ],
    })),
    // ── Cache-Control ──────────────────────────────────────────
    // HTML pages: never cache, always revalidate
    {
      source: '/:path*',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' },
      ],
    },
    // Next.js static assets (hashed filenames): immutable, 1 year
    {
      source: '/_next/static/:path*',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
      ],
    },
    // Next.js optimized images: 1 day + stale-while-revalidate
    {
      source: '/_next/image/:path*',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=86400, stale-while-revalidate=604800' },
      ],
    },
  ],
}

export default withNextIntl(analyzer(nextConfig))
