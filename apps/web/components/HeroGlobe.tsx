'use client';

import { useEffect, useRef, useState } from 'react';

type Props = {
  className?: string;
};

/**
 * Hero visual — rotating globe video. The asset (globe_baked.mp4) is an opaque
 * MP4 with the globe's original black background luma-keyed and re-composited
 * onto the hero color (#FAFAFA) — original colors kept, no tint. Since the hero
 * background is flat #FAFAFA, the globe blends in with no visible box/panel.
 * (Baked rather than a transparent VP9-alpha WebM because Chrome here renders
 * VP9 alpha as an opaque black box; opaque H.264 works in every browser.)
 * Loops forever, slowed to 0.5×, no cursor interaction. Respects
 * prefers-reduced-motion: no autoplay, shows the first frame paused.
 */
export default function HeroGlobe({ className }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Read once before first paint (client-only component) to avoid an autoplay flash.
  const [prefersReduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (prefersReduced) {
      // Stay on the first frame, no motion.
      video.pause();
      return;
    }

    // Slow the rotation; also set on loadedmetadata in case metadata isn't ready yet.
    video.playbackRate = 0.5;
  }, [prefersReduced]);

  return (
    <div
      className={className}
      style={{ width: '100%', height: '100%' }}
      aria-hidden="true"
    >
      <video
        ref={videoRef}
        src="/globe/globe_baked.mp4"
        autoPlay={!prefersReduced}
        muted
        loop
        playsInline
        preload="auto"
        aria-hidden="true"
        onLoadedMetadata={(e) => {
          if (!prefersReduced) e.currentTarget.playbackRate = 0.5;
        }}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          display: 'block',
        }}
      />
    </div>
  );
}
