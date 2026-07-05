'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Full-bleed looping video background for the dark marketing heroes
 * (pricing / how-it-works mesh, vision). Defaults to the pricing mesh asset.
 *
 * The assets are AI-generated clips with the black pillarbox bars cropped off
 * and the generator watermark removed (ffmpeg), re-encoded muted +
 * web-optimized. It sits behind the hero text via object-fit:
 * cover. Respects prefers-reduced-motion: no autoplay, stays on the poster frame.
 *
 * Black-screen guard: a dedicated poster layer (mesh first-frame) is ALWAYS
 * painted behind the video, with #0A0A0A only *behind* the poster as the
 * anti-white-flash measure. The video starts transparent and fades in only once
 * it is actually painting frames (onPlaying) — so on cold cache / throttled
 * playback / refused autoplay the user sees the gradient first-frame, never a
 * pure-black rectangle.
 *
 * Browser-only concern is just the reduced-motion read; rendered client-side so the
 * <video> never autoplays for users who asked for less motion.
 */
export default function MeshHeroVideo({
  src = '/pricing/mesh-bg.mp4',
  poster = '/pricing/mesh-poster.jpg',
}: {
  src?: string;
  poster?: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Read once before first paint to avoid an autoplay flash.
  const [prefersReduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  // Stay on the poster image until the video is *actually painting* frames, then
  // fade it in. onPlaying (not onLoadedData) guarantees we never reveal a still-
  // empty video and uncover the ink background.
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (prefersReduced) {
      video.pause(); // hold on the poster frame
      return;
    }
    // Some browsers reject autoplay even when muted (low battery / data saver).
    // Swallow the rejection so it never bubbles; the poster layer stays visible.
    const p = video.play();
    if (p && typeof p.catch === 'function') p.catch(() => {});
  }, [prefersReduced]);

  const showVideo = playing && !prefersReduced;

  return (
    <>
      {/* Poster layer: the mesh first-frame, ALWAYS painted above the ink
          background so the hero is never a pure-black rectangle while the video
          buffers or if autoplay is refused. #0A0A0A sits behind the image as the
          anti-white-flash fallback, not as the visible state. */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          backgroundColor: '#0A0A0A',
          backgroundImage: `url(${poster})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          zIndex: 0,
        }}
      />
      <video
        ref={videoRef}
        autoPlay={!prefersReduced}
        muted
        loop
        playsInline
        preload="auto"
        poster={poster}
        aria-hidden="true"
        onPlaying={() => setPlaying(true)}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          zIndex: 1,
          opacity: showVideo ? 1 : 0,
          transition: 'opacity 200ms ease',
        }}
      >
        <source src={src} type="video/mp4" />
      </video>
    </>
  );
}
