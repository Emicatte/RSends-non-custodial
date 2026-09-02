import type { ReactNode } from 'react'

/**
 * A browser window, drawn in CSS. Presentational: it takes children and knows
 * nothing about what is inside them.
 *
 * A browser window rather than a laptop body, deliberately. A laptop implies a
 * native app and this is a web product, and Apple hardware imagery carries a
 * licensing question not worth answering for a marketing section.
 *
 * Flat and orthographic — no `perspective`, no 3D `transform`. Live DOM sits
 * inside this frame, and perspective blurs real text and stops resolving at
 * small widths.
 */
export function BrowserFrame({
  url,
  children,
}: {
  /** Shown in the address bar. Decorative: never a link, never navigable. */
  url: string
  children: ReactNode
}) {
  return (
    <div
      data-frame="browser"
      style={{
        borderRadius: 12,
        overflow: 'hidden',
        background: '#ffffff',
        border: '1px solid rgba(10,10,10,0.10)',
        // The cast shadow is what lifts the window off the page; the second,
        // tight shadow keeps the edge from looking painted on.
        boxShadow: '0 32px 64px -16px rgba(10,10,10,0.22), 0 2px 6px rgba(10,10,10,0.06)',
      }}
    >
      {/* Chrome. Hidden from assistive technology as a whole: the traffic
          lights and the spacer already were, but the address bar was not, so a
          screen reader announced a host name that is decoration — not a link,
          not navigable, and nothing a listener can act on. The frame's contents
          are the real product and stay in the tree. */}
      <div
        aria-hidden="true"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 12px',
          height: 38,
          background: 'linear-gradient(180deg, #f6f5f2 0%, #eceae5 100%)',
          borderBottom: '1px solid rgba(10,10,10,0.09)',
        }}
      >
        <div style={{ display: 'flex', gap: 7, flexShrink: 0 }} aria-hidden="true">
          {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
            <span
              key={c}
              style={{
                width: 11,
                height: 11,
                borderRadius: '50%',
                background: c,
                boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,0.10)',
              }}
            />
          ))}
        </div>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            height: 22,
            borderRadius: 6,
            background: '#ffffff',
            border: '1px solid rgba(10,10,10,0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 10px',
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono, monospace)',
              fontSize: 11,
              color: 'rgba(10,10,10,0.45)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {url}
          </span>
        </div>
        {/* Balances the traffic lights so the address bar sits centred. */}
        <div style={{ width: 43, flexShrink: 0 }} aria-hidden="true" />
      </div>

      {/* Screen. The inset shadow is the seam between chrome and page. */}
      <div
        style={{
          position: 'relative',
          background: '#f7f6f3',
          boxShadow: 'inset 0 1px 3px rgba(10,10,10,0.06)',
        }}
      >
        {children}
      </div>
    </div>
  )
}
