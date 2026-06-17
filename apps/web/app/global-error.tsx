'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="it">
      <body style={{ background: '#FAFAFA', margin: 0 }}>
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
            color: 'rgba(10,10,10,0.55)',
            marginTop: 12,
          }}>
            {error.message || 'A critical error occurred'}
          </p>
          <button
            onClick={reset}
            style={{
              marginTop: 28,
              padding: '10px 24px',
              borderRadius: 10,
              background: 'rgba(200,81,44,0.15)',
              border: '1px solid rgba(200,81,44,0.25)',
              color: '#C8512C',
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
