'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  // global-error replaces the root layout, so globals.css is never loaded here
  // and var(--rs-*) would resolve to nothing. These literals are deliberate;
  // they mirror --rs-paper / --rs-ink / --rs-ink-muted / --rs-terracotta-deep.
  return (
    <html lang="it">
      <body style={{ background: '#EFEEEA', margin: 0 }}>
        <div style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#0A0A0A',
          fontFamily: 'system-ui, sans-serif',
        }}>
          <h1 style={{ fontSize: 48, fontWeight: 800, margin: 0 }}>Something went wrong</h1>
          <p style={{
            fontSize: 13,
            color: '#55534E',
            marginTop: 12,
          }}>
            {error.message || 'A critical error occurred'}
          </p>
          <button
            onClick={reset}
            style={{
              marginTop: 28,
              padding: '10px 24px',
              borderRadius: 4,
              background: '#F6E6DF',
              border: '1px solid rgba(168,64,31,0.25)',
              // terracotta-deep, not terracotta: this is 13px text.
              color: '#A8401F',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
