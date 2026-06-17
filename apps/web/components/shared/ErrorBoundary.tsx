'use client'

import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  module?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[RSend:${this.props.module || 'Unknown'}] Render crash:`, error, info)
    // Sentry: Sentry.captureException(error, { extra: { componentStack: info.componentStack } })
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div style={{
          padding: 24, textAlign: 'center',
          background: 'rgba(255,76,106,0.05)',
          border: '1px solid rgba(255,76,106,0.15)',
          borderRadius: 14, margin: 12,
        }}>
          <div style={{ fontSize: 24, marginBottom: 8 }}>⚠</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 600, color: '#0A0A0A', marginBottom: 4 }}>
            Something went wrong
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(10,10,10,0.55)', marginBottom: 12 }}>
            {this.state.error?.message || 'Unexpected error'}
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              padding: '8px 20px', borderRadius: 10, border: 'none',
              background: 'rgba(10,10,10,0.08)', color: '#0A0A0A',
              fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
