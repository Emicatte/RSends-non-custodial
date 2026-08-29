export default function NotFound() {
  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#FAFAFA',
      color: '#0A0A0A',
      fontFamily: 'var(--font-display)',
    }}>
      <h1 style={{ fontSize: 72, fontWeight: 800, margin: 0, lineHeight: 1 }}>404</h1>
      <p style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 14,
        color: 'rgba(10,10,10,0.55)',
        marginTop: 12,
      }}>
        Page not found
      </p>
      <a
        href="/"
        style={{
          marginTop: 28,
          padding: '10px 24px',
          borderRadius: 10,
          background: 'rgba(200,81,44,0.15)',
          border: '1px solid rgba(200,81,44,0.25)',
          color: '#C8512C',
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          textDecoration: 'none',
        }}
      >
        Back to home
      </a>
    </div>
  )
}
