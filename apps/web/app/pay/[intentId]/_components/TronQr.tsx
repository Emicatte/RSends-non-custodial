'use client'

/**
 * TronQr — a QR of the BARE address, and nothing else.
 *
 * Not a payment URI. There is no EIP-681 equivalent on TRON, and the
 * amount-embedding formats that exist are not read uniformly across wallets —
 * an exchange withdrawal screen, which is how a large share of TRON payments
 * are actually sent, scans for an address and would reject or mis-read a
 * scheme-prefixed string. A bare address is the one encoding every scanner
 * agrees on. The amount is beside the code, in text, copyable.
 *
 * `qrcode` is already a dependency (the admin 2FA route uses it server-side).
 * Its `create()` returns the module bitmap directly, which is rendered here as
 * plain SVG rects: no canvas (so it works under jsdom), no data URL, and no
 * dangerouslySetInnerHTML on a payer-facing page.
 */

import { useMemo } from 'react'
import QRCode from 'qrcode'

/** Quiet zone, in modules. The spec asks for 4; scanners want it. */
const MARGIN = 4

export function TronQr({ value, size = 176 }: { value: string; size?: number }) {
  const path = useMemo(() => {
    const { modules } = QRCode.create(value, { errorCorrectionLevel: 'M' })
    const count = modules.size
    const cells: string[] = []
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) {
        if (modules.data[row * count + col]) {
          cells.push(`M${col + MARGIN} ${row + MARGIN}h1v1h-1z`)
        }
      }
    }
    return { d: cells.join(''), extent: count + MARGIN * 2 }
  }, [value])

  return (
    <svg
      // The encoded value, exposed so a test can assert that what the payer
      // scans is byte-identical to what the page displays and copies.
      data-qr-value={value}
      role="img"
      aria-label={value}
      width={size}
      height={size}
      viewBox={`0 0 ${path.extent} ${path.extent}`}
      shapeRendering="crispEdges"
      style={{ display: 'block', borderRadius: 8 }}
    >
      <rect width={path.extent} height={path.extent} fill="#FFFFFF" />
      <path d={path.d} fill="#0A0A0A" />
    </svg>
  )
}

export default TronQr
