'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Full-bleed looping mesh-gradient background for the pricing hero.
 *
 * The asset (public/pricing/mesh-bg.mp4) is the AI-generated mesh clip with the
 * black pillarbox bars cropped off and the generator watermark removed (ffmpeg),
 * re-encoded muted + web-optimized. It sits behind the hero text via object-fit:
 * cover. Respects prefers-reduced-motion: no autoplay, stays on the poster frame.
 *
 * Browser-only concern is just the reduced-motion read; rendered client-side so the
 * <video> never autoplays for users who asked for less motion.
 */
export default function MeshHeroVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Read once before first paint to avoid an autoplay flash.
  const [prefersReduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  // Keep the video transparent until it has data, then fade it in over the ink
  // background so navigating to the page never shows a white/empty flash.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (video && prefersReduced) video.pause(); // hold on the poster frame
  }, [prefersReduced]);

  return (
    <video
      ref={videoRef}
      autoPlay={!prefersReduced}
      muted
      loop
      playsInline
      preload="auto"
      poster="/pricing/mesh-poster.jpg"
      aria-hidden="true"
      onLoadedData={() => setReady(true)}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        zIndex: 0,
        backgroundColor: '#0A0A0A', // ink box → never a white flash while loading
        opacity: prefersReduced || ready ? 1 : 0,
        transition: 'opacity 200ms ease',
      }}
    >
      <source src="/pricing/mesh-bg.mp4" type="video/mp4" />
    </video>
  );
}
