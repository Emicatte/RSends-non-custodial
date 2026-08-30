// Lets TSX recognize the <rsends-globe> custom element (see lib/rsends-globe.js).
import type { DetailedHTMLProps, HTMLAttributes } from 'react'

declare global {
  namespace JSX {
    interface IntrinsicElements {
      'rsends-globe': DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        'rotation-seconds'?: string | number
        tilt?: string | number
        accent?: string
        ink?: string
        'label-color'?: string
        halo?: string
        'show-labels'?: string
        'show-routes'?: string
        paused?: string
      }
    }
  }
}

export {}
