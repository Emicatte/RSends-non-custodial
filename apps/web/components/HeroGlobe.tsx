'use client';

import { C } from '@/app/designTokens';
// Side-effect import: executes the IIFE in rsends-globe.js, which registers the
// <rsends-globe> custom element via customElements.define(). This module is only
// evaluated in the browser because HeroGlobe is imported with { ssr: false }
// (app/[locale]/page.tsx), so the browser-only canvas/window code never runs on the server.
import '@/lib/rsends-globe';

type Props = {
  className?: string;
};

/**
 * Hero visual — the rotating dotted globe with terracotta payment routes.
 *
 * Renders the self-contained <rsends-globe> custom element (lib/rsends-globe.js):
 * a dependency-free <canvas> drawing Natural Earth land as dots, spinning 360° in
 * a ~45s loop, with great-circle route arcs + travelling packets between cities.
 * The element handles its own crispness (devicePixelRatio), off-screen pause
 * (IntersectionObserver), and prefers-reduced-motion (one static frame), so this
 * wrapper only needs to register the element and size it.
 *
 * Browser-only (canvas + window): this component is mounted client-side only
 * (imported with { ssr: false } in app/[locale]/page.tsx).
 */
export default function HeroGlobe({ className }: Props) {
  return (
    <div
      className={className}
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      aria-hidden="true"
    >
      {/* <rsends-globe> has no intrinsic size and sizes its square canvas to its OWN
          width (clientWidth), so the wrapper needs a DEFINITE width to paint. We give it
          an explicit width here; the globe is 1:1 and derives its own height from that
          width via width:100% (no aspect-ratio / height:100% — a height-derived width can
          collapse to 0 and the canvas paints invisibly). maxWidth keeps it bounded.
          City-name labels stay off (show-labels="false"): the only caption the
          globe carries is the active arc's chain·token, drawn by the element
          itself. `halo` is the knockout behind that caption and must track the
          page background, so it is passed rather than left on its default. */}
      <div style={{ width: 'min(560px, 42vw)', maxWidth: '100%', margin: '0 auto' }}>
        <rsends-globe
          rotation-seconds="45"
          tilt="20"
          accent={C.terracotta}
          ink={C.text}
          halo={C.bg}
          show-labels="false"
          style={{ display: 'block', width: '100%' }}
        />
      </div>
    </div>
  );
}
