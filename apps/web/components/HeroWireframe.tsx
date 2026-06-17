'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

type Props = {
  className?: string;
};

export default function HeroWireframe({ className }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || typeof window === 'undefined') return;

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let W = mount.clientWidth;
    let H = mount.clientHeight;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
    camera.position.z = 5.5;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);

    const outerGeo = new THREE.IcosahedronGeometry(1.7, 2);
    const outerWire = new THREE.WireframeGeometry(outerGeo);
    const outerMat = new THREE.LineBasicMaterial({
      color: 0xc8512c,
      transparent: true,
      opacity: 0.9,
    });
    const outer = new THREE.LineSegments(outerWire, outerMat);
    scene.add(outer);

    const innerGeo = new THREE.IcosahedronGeometry(1.0, 1);
    const innerWire = new THREE.WireframeGeometry(innerGeo);
    const innerMat = new THREE.LineBasicMaterial({
      color: 0x0a0a0a,
      transparent: true,
      opacity: 0.25,
    });
    const inner = new THREE.LineSegments(innerWire, innerMat);
    scene.add(inner);

    const dotsGeo = new THREE.BufferGeometry();
    const dotsCount = 60;
    const positions = new Float32Array(dotsCount * 3);
    for (let i = 0; i < dotsCount; i++) {
      const r = 2.3 + Math.random() * 0.8;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    dotsGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const dotsMat = new THREE.PointsMaterial({
      color: 0x0a0a0a,
      size: 0.04,
      transparent: true,
      opacity: 0.5,
    });
    const dots = new THREE.Points(dotsGeo, dotsMat);
    scene.add(dots);

    let mx = 0, my = 0, tmx = 0, tmy = 0;

    const onMouseMove = (e: MouseEvent) => {
      const r = mount.getBoundingClientRect();
      tmx = ((e.clientX - r.left) / r.width) * 2 - 1;
      tmy = -(((e.clientY - r.top) / r.height) * 2 - 1);
    };
    // Listen on window so wireframe reacts even when cursor is over overlapping elements
    window.addEventListener('mousemove', onMouseMove);

    const onResize = () => {
      if (!mount) return;
      W = mount.clientWidth;
      H = mount.clientHeight;
      if (W === 0 || H === 0) return;
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    const clock = new THREE.Clock();
    let rafId = 0;
    const animate = () => {
      const t = clock.getElapsedTime();

      if (!prefersReduced) {
        mx += (tmx - mx) * 0.06;
        my += (tmy - my) * 0.06;

        outer.rotation.y = t * 0.18 + mx * 0.7;
        outer.rotation.x = t * 0.12 + my * 0.7;

        inner.rotation.y = -t * 0.22 - mx * 0.4;
        inner.rotation.x = -t * 0.14 - my * 0.4;

        dots.rotation.y = t * 0.05 + mx * 0.2;
        dots.rotation.x = my * 0.15;

        const s = 1 + Math.sin(t * 1.1) * 0.025;
        outer.scale.setScalar(s);
      }

      renderer.render(scene, camera);
      rafId = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('mousemove', onMouseMove);
      ro.disconnect();
      outerGeo.dispose();
      outerWire.dispose();
      outerMat.dispose();
      innerGeo.dispose();
      innerWire.dispose();
      innerMat.dispose();
      dotsGeo.dispose();
      dotsMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className={className}
      style={{ width: '100%', height: '100%' }}
      aria-hidden="true"
    />
  );
}
