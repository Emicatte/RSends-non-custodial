'use client'

interface FeatureDisabledProps {
  message: string
}

export default function FeatureDisabled({ message }: FeatureDisabledProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        padding: '2rem',
        borderRadius: 12,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(255,255,255,0.02)',
        color: 'rgba(255,255,255,0.7)',
        textAlign: 'center',
        fontSize: '0.95rem',
      }}
    >
      {message}
    </div>
  )
}
