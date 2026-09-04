import type { ReactNode } from 'react'

/**
 * A phone, drawn in CSS. Presentational: children only.
 *
 * Flat and orthographic for the same reason as BrowserFrame — live DOM sits
 * inside it, and perspective would blur real text.
 *
 * The thin bright inner ring is what makes the black band read as a bezel
 * rather than as a border: on a real device that highlight is the chamfered
 * edge catching light. Without it the frame looks like a rectangle with a
 * thick outline.
 */
export function PhoneFrame({
  statusTime = '9:41',
  children,
}: {
  /** Decorative. Fixed, never a clock: a live one would differ between the
   *  server render and the client and tear the React root. */
  statusTime?: string
  children: ReactNode
}) {
  return (
    <div
      data-frame="phone"
      style={{
        borderRadius: 42,
        padding: 8,
        background: 'linear-gradient(160deg, #2a2a2a 0%, #0d0d0d 55%, #1c1c1c 100%)',
        boxShadow:
          '0 32px 64px -16px rgba(10,10,10,0.30), 0 2px 6px rgba(10,10,10,0.10), inset 0 0 0 1px rgba(255,255,255,0.14)',
      }}
    >
      <div
        style={{
          position: 'relative',
          borderRadius: 35,
          overflow: 'hidden',
          background: '#f7f6f3',
        }}
      >
        {/* Status bar. Its height is what the Dynamic Island sits inside, so
            content below never collides with it.

            Hidden from assistive technology as a whole. The signal bars and the
            island already were; the time was not, so a screen reader announced
            "9:41" between the merchant dashboard and the payer's receipt — a
            mock clock is scenery, and there is nothing a listener can do with
            it. The checkout inside the frame is the real product and stays in
            the tree. Same defect as the browser chrome's address bar. */}
        <div
          aria-hidden="true"
          style={{
            position: 'relative',
            height: 40,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 20px',
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            fontWeight: 700,
            color: '#0a0a0a',
          }}
        >
          <span>{statusTime}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }} aria-hidden="true">
            {/* Signal, wifi, battery — bars, not glyphs, so nothing depends on
                an icon font resolving. */}
            {[4, 6, 8, 10].map((h) => (
              <span key={h} style={{ width: 3, height: h, borderRadius: 1, background: '#0a0a0a' }} />
            ))}
            <span
              style={{
                marginLeft: 4,
                width: 22,
                height: 11,
                borderRadius: 3,
                border: '1px solid rgba(10,10,10,0.45)',
                padding: 1.5,
                display: 'inline-flex',
              }}
            >
              <span style={{ flex: 1, borderRadius: 1, background: '#0a0a0a' }} />
            </span>
          </div>
        </div>

        {/* Dynamic Island */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 9,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 86,
            height: 24,
            borderRadius: 14,
            background: '#0a0a0a',
          }}
        />

        {children}

        {/* Home indicator */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            bottom: 7,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 106,
            height: 4,
            borderRadius: 2,
            background: 'rgba(10,10,10,0.30)',
          }}
        />
      </div>
    </div>
  )
}
