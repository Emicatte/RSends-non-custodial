'use client'

import { useRef, useEffect, useCallback, useState } from 'react'
import { Link } from '@/i18n/navigation'
import styles from './FooterGlobe.module.css'

// ═══════════════════════════════════════════════════════════
//  CONSTANTS & PALETTE
// ═══════════════════════════════════════════════════════════

const SPHERE_R_RATIO = 0.32 // radius relative to min(w,h)
const AUTO_ROTATE = 0.00012
const LERP = 0.04

// ── Cities [lat, lon, name] ──
const CITIES: [number, number, string][] = [
  [51.5,  -0.1,   'London'],
  [40.7,  -74.0,  'New York'],
  [-23.5, -46.6,  'São Paulo'],
  [25.2,   55.3,  'Dubai'],
  [19.1,   72.9,  'Mumbai'],
  [1.3,   103.8,  'Singapore'],
  [35.7,  139.7,  'Tokyo'],
  [34.0, -118.2,  'Los Angeles'],
  [50.1,    8.7,  'Frankfurt'],
  [37.6,  126.9,  'Seoul'],
  [37.8, -122.4,  'San Francisco'],
  [45.5,    9.2,  'Milan'],
  [-34.6, -58.4,  'Buenos Aires'],
]

// ── Arcs [fromIdx, toIdx, colorHex] ──
const ARCS: [number, number, string][] = [
  [0,  1,  '#ff2d78'], // London → NY
  [1,  2,  '#a855f7'], // NY → São Paulo
  [0,  3,  '#3b82f6'], // London → Dubai
  [3,  4,  '#ff2d78'], // Dubai → Mumbai
  [4,  5,  '#a855f7'], // Mumbai → Singapore
  [5,  6,  '#3b82f6'], // Singapore → Tokyo
  [6,  7,  '#ff2d78'], // Tokyo → LA
  [8,  5,  '#a855f7'], // Frankfurt → Singapore
  [9, 10,  '#3b82f6'], // Seoul → SF
  [11, 2,  '#ff2d78'], // Milan → Buenos Aires
]

// ── Token badges ──
const TOKENS = [
  { sym: 'BTC',   color: '#f7931a', lat: 40,  lon: -100 },
  { sym: 'ETH',   color: '#627eea', lat: 50,  lon: 10   },
  { sym: 'SOL',   color: '#9945ff', lat: 35,  lon: 140  },
  { sym: 'TRX',   color: '#ef0027', lat: 15,  lon: 105  },
  { sym: 'USDC',  color: '#2775ca', lat: 30,  lon: -40  },
  { sym: 'MATIC', color: '#8247e5', lat: -20, lon: -60  },
  { sym: 'BNB',   color: '#f3ba2f', lat: 25,  lon: 55   },
  { sym: 'OP',    color: '#ff0420', lat: 20,  lon: -150 },
]

// ── ~500 representative land coordinates ──
const LAND: [number, number][] = [
  // North America
  [71,-156],[70,-145],[68,-135],[65,-168],[64,-140],[63,-151],[62,-130],
  [61,-150],[60,-135],[60,-120],[59,-140],[58,-134],[57,-153],[56,-130],
  [55,-132],[54,-128],[53,-122],[52,-128],[51,-120],[50,-127],[50,-115],
  [49,-123],[49,-88],[48,-123],[48,-89],[47,-122],[47,-84],[46,-90],
  [45,-122],[45,-75],[44,-79],[44,-69],[43,-89],[43,-70],[42,-83],
  [42,-71],[41,-74],[40,-74],[40,-80],[40,-112],[39,-77],[39,-105],
  [38,-90],[38,-122],[37,-76],[37,-122],[36,-96],[36,-115],[35,-80],
  [35,-106],[34,-84],[34,-118],[33,-97],[33,-112],[32,-96],[32,-117],
  [31,-97],[30,-90],[30,-97],[29,-95],[28,-82],[27,-80],[26,-80],
  [25,-80],[24,-110],[23,-110],[22,-105],[21,-105],[20,-99],[19,-99],
  [18,-96],[17,-96],[16,-90],[15,-88],
  // Central America / Caribbean
  [14,-87],[13,-85],[12,-84],[10,-84],[9,-79],[8,-77],[23,-82],
  [22,-80],[20,-76],[19,-72],[18,-70],[18,-66],
  // South America
  [10,-67],[8,-63],[7,-58],[5,-55],[4,-52],[2,-50],[0,-50],[-2,-44],
  [-4,-38],[-5,-35],[-7,-35],[-8,-35],[-10,-37],[-12,-38],[-13,-44],
  [-15,-47],[-16,-49],[-18,-43],[-20,-44],[-22,-43],[-23,-46],
  [-25,-49],[-27,-49],[-28,-49],[-29,-51],[-30,-51],[-32,-52],
  [-33,-53],[-34,-58],[-35,-57],[-37,-57],[-38,-62],[-40,-65],
  [-42,-65],[-45,-67],[-47,-66],[-49,-69],[-51,-69],[-53,-70],
  [-54,-68],[-1,-78],[-2,-80],[-5,-80],[-7,-79],[-10,-76],[-12,-77],
  [-14,-76],[-16,-70],[-18,-64],[-20,-64],[-22,-65],
  [5,-74],[4,-72],[7,-72],[10,-72],[11,-74],[12,-72],
  // Europe
  [71,28],[70,26],[69,18],[68,16],[67,15],[66,14],[65,13],[64,11],
  [63,10],[62,6],[61,5],[60,5],[60,25],[59,18],[59,10],[58,12],
  [58,6],[57,10],[57,-7],[56,10],[56,-5],[55,12],[55,-3],[54,10],
  [54,-6],[53,7],[53,-1],[52,5],[52,-2],[51,4],[51,-3],[51,0],
  [50,4],[50,14],[49,2],[49,16],[48,2],[48,16],[47,2],[47,15],
  [46,6],[46,15],[45,9],[45,14],[44,12],[44,1],[43,3],[43,12],
  [42,3],[42,12],[41,2],[41,12],[40,-4],[40,24],[39,-9],[39,22],
  [38,-9],[38,24],[37,-8],[37,24],[36,-6],[36,28],[35,25],[35,33],
  // Africa
  [37,10],[36,3],[35,0],[34,-1],[33,-5],[32,-5],[31,-6],[30,-10],
  [30,32],[28,-10],[27,-13],[26,-14],[25,-13],[24,-15],[22,-17],
  [20,-17],[18,-16],[16,-16],[15,-17],[14,-17],[13,-15],[12,-12],
  [11,-8],[10,-8],[9,-5],[8,-5],[7,-5],[6,-3],[5,-4],[4,9],
  [3,10],[2,10],[1,10],[0,9],[-1,12],[-2,17],[-3,12],[-4,12],
  [-5,13],[-6,12],[-7,13],[-8,14],[-9,13],[-10,34],[-11,35],
  [-12,34],[-13,33],[-14,33],[-15,35],[-16,35],[-17,36],[-18,36],
  [-19,35],[-20,35],[-22,35],[-24,32],[-26,28],[-28,27],[-30,28],
  [-32,28],[-34,26],[10,40],[12,42],[14,43],[11,43],[8,46],
  [5,42],[0,42],[-2,40],[-4,38],[-6,39],[-8,40],
  [30,32],[28,30],[26,32],[24,33],[22,36],[20,38],[18,40],
  // Asia (West / Central)
  [42,60],[40,50],[40,68],[38,48],[38,58],[36,52],[36,60],
  [34,50],[34,72],[32,48],[32,52],[30,48],[30,67],[28,50],[28,68],
  [26,50],[26,56],[24,47],[24,54],[22,46],[20,42],[18,42],
  [16,43],[14,43],[12,44],[42,44],[40,44],[38,44],[36,44],
  // Asia (East)
  [52,60],[50,80],[48,68],[48,87],[46,75],[46,90],[44,80],
  [44,130],[42,77],[42,128],[40,116],[38,115],[36,103],[36,120],
  [34,109],[34,118],[32,105],[32,119],[30,90],[30,104],[30,120],
  [28,84],[28,86],[28,96],[28,104],[26,80],[26,100],[24,91],
  [24,102],[22,88],[22,100],[22,108],[20,78],[20,96],[20,106],
  [18,76],[18,100],[16,80],[16,108],[14,100],[12,102],[10,99],
  [8,80],[6,100],[4,102],[2,104],[1,104],
  // Russia / Siberia
  [68,33],[66,40],[64,40],[62,40],[60,30],[60,56],[60,73],[60,90],
  [60,120],[58,50],[58,68],[58,93],[58,130],[56,44],[56,60],
  [56,83],[56,93],[56,110],[56,130],[54,37],[54,50],[54,73],
  [54,84],[54,108],[54,130],[52,40],[52,47],[52,80],[52,104],
  [52,113],[52,130],[52,140],[50,40],[50,127],[50,132],[50,142],
  [48,135],[46,135],[44,132],[43,132],[64,178],[62,170],[60,165],
  [58,160],[56,160],[54,160],[52,158],
  // Japan
  [43,141],[42,140],[40,140],[38,140],[36,140],[35,135],[34,131],
  [33,130],[32,131],[31,131],
  // Korea
  [38,127],[37,127],[36,127],[35,129],[34,127],
  // SE Asia / Indonesia
  [0,110],[-2,106],[-3,105],[-5,105],[-6,106],[-7,110],[-8,112],
  [-8,115],[-8,122],[-8,131],[-6,134],[-4,122],[-2,117],[0,117],
  [2,111],[4,115],[6,116],[5,118],
  // Australia
  [-12,131],[-14,130],[-16,130],[-18,126],[-20,119],[-22,114],
  [-24,114],[-26,113],[-28,114],[-30,116],[-32,116],[-33,118],
  [-34,116],[-35,117],[-35,138],[-34,140],[-33,148],[-32,152],
  [-30,153],[-28,153],[-26,149],[-24,150],[-22,149],[-20,147],
  [-18,146],[-16,145],[-14,136],[-12,136],[-14,143],[-16,146],
  [-38,145],[-37,150],[-36,148],[-34,151],
  // New Zealand
  [-36,174],[-38,176],[-40,176],[-42,172],[-44,170],[-46,168],
  // India / Sri Lanka
  [28,73],[26,70],[24,73],[22,69],[20,73],[18,73],[16,73],
  [14,77],[12,80],[10,77],[8,77],[7,80],
  // Middle East
  [33,44],[31,36],[30,35],[29,35],[28,36],[27,37],[25,37],
  [24,39],[22,39],[20,40],[18,42],[15,44],[13,45],
  // Extra: North America fill
  [55,-110],[53,-115],[51,-110],[49,-100],[48,-95],[47,-95],[46,-95],
  [45,-85],[44,-85],[43,-80],[42,-88],[41,-88],[40,-86],[39,-95],
  [38,-95],[37,-95],[36,-90],[35,-90],[34,-90],[33,-88],[32,-90],
  [31,-92],[30,-95],[29,-98],[28,-97],[27,-97],[26,-97],[25,-97],
  [50,-100],[48,-110],[46,-110],[44,-110],[42,-110],[40,-100],[38,-100],
  // Extra: Europe fill
  [48,8],[47,8],[46,8],[45,7],[44,8],[43,8],[42,8],[50,8],[49,8],
  [55,8],[54,8],[53,8],[52,8],[51,8],[48,12],[47,12],[46,12],
  [45,12],[44,10],[43,10],[42,10],[55,20],[53,20],[51,20],[49,20],
  [47,20],[45,20],[43,20],[41,20],[50,30],[48,30],[46,30],[44,28],
  [42,28],[40,28],[55,38],[53,38],[51,38],[49,38],
  // Extra: Africa interior
  [20,10],[18,10],[16,10],[14,10],[12,10],[10,10],[8,10],[6,10],
  [4,18],[2,18],[0,18],[-2,18],[-4,18],[20,20],[18,20],[16,20],
  [14,20],[12,20],[10,20],[8,20],[6,20],[4,20],[2,20],[0,20],
  [20,30],[18,30],[16,30],[14,30],[12,30],[10,30],[8,30],[6,30],
  [-2,30],[-4,30],[-6,30],[-8,30],[-10,30],[-12,30],[-14,30],
  [15,30],[13,32],[11,34],[9,36],[7,38],[5,38],[3,36],[1,34],
  // Extra: Russia/Central Asia
  [50,50],[48,50],[46,50],[44,50],[42,50],[50,60],[48,60],[46,60],
  [50,70],[48,70],[46,70],[44,70],[50,90],[48,90],[46,90],[44,90],
  [50,100],[48,100],[46,100],[44,100],[50,110],[48,110],[46,110],
  [50,120],[48,120],[46,120],[44,120],
  // Extra: China/SE Asia fill
  [36,110],[34,110],[32,110],[30,110],[28,110],[26,110],[24,110],
  [22,110],[20,110],[18,110],[16,110],[14,110],[12,110],
  [30,95],[28,95],[26,95],[24,95],[22,95],[20,95],
  // Extra: South America interior
  [-5,-50],[-7,-50],[-9,-50],[-11,-50],[-13,-50],[-15,-50],
  [-5,-60],[-7,-60],[-9,-60],[-11,-60],[-13,-60],[-15,-60],
  [-17,-55],[-19,-55],[-21,-55],[-23,-55],[-25,-55],[-27,-55],
  [0,-65],[0,-70],[-2,-70],[-4,-70],[-6,-70],[-8,-65],[-10,-65],
]

// ═══════════════════════════════════════════════════════════
//  3D MATH (identical projection math, pure JS)
// ═══════════════════════════════════════════════════════════

interface V3 { x: number; y: number; z: number }

function ll2v(lat: number, lon: number, r: number): V3 {
  const p = (90 - lat) * (Math.PI / 180)
  const t = (lon + 180) * (Math.PI / 180)
  return { x: -r * Math.sin(p) * Math.cos(t), y: r * Math.cos(p), z: r * Math.sin(p) * Math.sin(t) }
}

function rotY(v: V3, a: number): V3 {
  const c = Math.cos(a), s = Math.sin(a)
  return { x: v.x * c + v.z * s, y: v.y, z: -v.x * s + v.z * c }
}

function rotX(v: V3, a: number): V3 {
  const c = Math.cos(a), s = Math.sin(a)
  return { x: v.x, y: v.y * c - v.z * s, z: v.y * s + v.z * c }
}

function proj(v: V3, cx: number, cy: number, fov: number): { x: number; y: number; s: number; vis: boolean } {
  const z = v.z + fov
  if (z < 1) return { x: 0, y: 0, s: 0, vis: false }
  const s = fov / z
  return { x: cx + v.x * s, y: cy - v.y * s, s, vis: true }
}

function transform(v: V3, ry: number, rx: number): V3 {
  return rotX(rotY(v, ry), rx)
}

// Bezier arc midpoint lifted above sphere surface
function arcMid(a: V3, b: V3, r: number, lift: number): V3 {
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const mz = (a.z + b.z) / 2
  const len = Math.sqrt(mx * mx + my * my + mz * mz) || 1
  const s = (r + lift) / len
  return { x: mx * s, y: my * s, z: mz * s }
}

// Quadratic bezier interpolation
function qbez(a: V3, ctrl: V3, b: V3, t: number): V3 {
  const u = 1 - t
  return {
    x: u * u * a.x + 2 * u * t * ctrl.x + t * t * b.x,
    y: u * u * a.y + 2 * u * t * ctrl.y + t * t * b.y,
    z: u * u * a.z + 2 * u * t * ctrl.z + t * t * b.z,
  }
}

// ═══════════════════════════════════════════════════════════
//  PRE-BAKED LAND DOTS (generated once, scattered ~12k points)
// ═══════════════════════════════════════════════════════════

function bakeLandDots(): V3[] {
  const dots: V3[] = []
  const jit = 2.2
  for (const [lat, lon] of LAND) {
    for (let i = 0; i < 50; i++) {
      dots.push(ll2v(
        lat + (Math.random() - 0.5) * jit * 2,
        lon + (Math.random() - 0.5) * jit * 2,
        1, // unit sphere, scaled at render time
      ))
    }
  }
  return dots
}

// ═══════════════════════════════════════════════════════════
//  GLOBE CANVAS
// ═══════════════════════════════════════════════════════════

function GlobeCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const mouseRef = useRef({ x: 0, y: 0 })
  const tiltRef = useRef({ x: 0, y: 0 })
  const frameRef = useRef(0)
  const landRef = useRef<V3[] | null>(null)

  const handleMouse = useCallback((e: MouseEvent) => {
    if (!wrapRef.current) return
    const r = wrapRef.current.getBoundingClientRect()
    mouseRef.current = {
      x: ((e.clientX - r.left) / r.width - 0.5) * 2,
      y: ((e.clientY - r.top) / r.height - 0.5) * 2,
    }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Bake land dots once
    if (!landRef.current) landRef.current = bakeLandDots()
    const landDots = landRef.current

    let running = true
    let dpr = 1

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio, 2)
      const rect = wrap.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = (time: number) => {
      if (!running) return
      const w = canvas.width / dpr
      const h = canvas.height / dpr
      const cx = w / 2
      const cy = h / 2
      const R = Math.min(w, h) * SPHERE_R_RATIO
      const fov = R * 3.5
      const isMobile = w < 600

      // Smooth tilt
      tiltRef.current.x += (mouseRef.current.y * 0.25 - tiltRef.current.x) * LERP
      tiltRef.current.y += (mouseRef.current.x * 0.25 - tiltRef.current.y) * LERP
      const rx = tiltRef.current.x
      const ry = tiltRef.current.y + time * AUTO_ROTATE

      ctx.clearRect(0, 0, w, h)

      // ── Outer ambient glow ──
      const grd = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 2.0)
      grd.addColorStop(0, 'rgba(100, 80, 220, 0.06)')
      grd.addColorStop(0.5, 'rgba(60, 40, 180, 0.02)')
      grd.addColorStop(1, 'transparent')
      ctx.fillStyle = grd
      ctx.fillRect(0, 0, w, h)

      // ── Solid dark sphere ──
      const sphereGrad = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.2, R * 0.05, cx, cy, R)
      sphereGrad.addColorStop(0, 'rgba(20, 22, 40, 0.95)')
      sphereGrad.addColorStop(0.7, 'rgba(12, 14, 30, 0.97)')
      sphereGrad.addColorStop(1, 'rgba(8, 10, 24, 0.98)')
      ctx.beginPath()
      ctx.arc(cx, cy, R, 0, Math.PI * 2)
      ctx.fillStyle = sphereGrad
      ctx.fill()

      // ── Rim light (edge glow) ──
      const rimGrad = ctx.createRadialGradient(cx, cy, R * 0.88, cx, cy, R * 1.08)
      rimGrad.addColorStop(0, 'transparent')
      rimGrad.addColorStop(0.5, 'rgba(120, 80, 255, 0.12)')
      rimGrad.addColorStop(0.75, 'rgba(80, 140, 255, 0.08)')
      rimGrad.addColorStop(1, 'transparent')
      ctx.beginPath()
      ctx.arc(cx, cy, R * 1.08, 0, Math.PI * 2)
      ctx.fillStyle = rimGrad
      ctx.fill()

      // ── Sphere outline ──
      ctx.beginPath()
      ctx.arc(cx, cy, R, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(100, 120, 220, 0.15)'
      ctx.lineWidth = 1.2
      ctx.stroke()

      // ── Land dots (bright cyan on dark sphere) ──
      // Clip to sphere so dots don't bleed outside
      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, R - 0.5, 0, Math.PI * 2)
      ctx.clip()

      for (const d of landDots) {
        const v = transform({ x: d.x * R, y: d.y * R, z: d.z * R }, ry, rx)
        const p = proj(v, cx, cy, fov)
        if (!p.vis) continue
        // Only draw front-facing dots (z > 0 after transform means facing us)
        if (v.z < -R * 0.05) continue
        const depthFactor = (v.z + R) / (2 * R) // 0=back, 1=front
        const alpha = 0.15 + depthFactor * 0.7
        const radius = Math.max(0.5, (0.6 + depthFactor * 0.7) * p.s)
        ctx.fillStyle = `rgba(80, 190, 255, ${alpha})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.restore()

      // ── Neon arcs + traveling pulses ──
      for (let ai = 0; ai < ARCS.length; ai++) {
        const [iA, iB, color] = ARCS[ai]
        const cityA = CITIES[iA]
        const cityB = CITIES[iB]
        const vA = ll2v(cityA[0], cityA[1], R)
        const vB = ll2v(cityB[0], cityB[1], R)
        const lift = 0.8 + (ai % 3) * 0.15
        const mid = arcMid(vA, vB, R, R * lift * 0.35)
        const pulse = (Math.sin(time * 0.001 + ai * 1.3) + 1) * 0.5

        // Glow layer (wider, softer)
        const segs = 50
        ctx.lineWidth = 3
        ctx.strokeStyle = color
        ctx.globalAlpha = 0.08 + pulse * 0.08
        ctx.shadowColor = color
        ctx.shadowBlur = 15
        ctx.beginPath()
        let started = false
        for (let s = 0; s <= segs; s++) {
          const t = s / segs
          const raw = qbez(vA, mid, vB, t)
          const v = transform(raw, ry, rx)
          const p = proj(v, cx, cy, fov)
          if (!p.vis) { started = false; continue }
          if (!started) { ctx.moveTo(p.x, p.y); started = true }
          else ctx.lineTo(p.x, p.y)
        }
        ctx.stroke()
        ctx.shadowBlur = 0
        ctx.globalAlpha = 1

        // Core line (thinner, brighter)
        ctx.lineWidth = 1.5
        ctx.strokeStyle = color
        ctx.globalAlpha = 0.4 + pulse * 0.4
        ctx.beginPath()
        started = false
        for (let s = 0; s <= segs; s++) {
          const t = s / segs
          const raw = qbez(vA, mid, vB, t)
          const v = transform(raw, ry, rx)
          const p = proj(v, cx, cy, fov)
          if (!p.vis) { started = false; continue }
          if (!started) { ctx.moveTo(p.x, p.y); started = true }
          else ctx.lineTo(p.x, p.y)
        }
        ctx.stroke()
        ctx.globalAlpha = 1

        // Traveling pulse dot
        const dotT = ((time * 0.0003 + ai * 0.37) % 1)
        const dotRaw = qbez(vA, mid, vB, dotT)
        const dotV = transform(dotRaw, ry, rx)
        const dotP = proj(dotV, cx, cy, fov)
        if (dotP.vis) {
          ctx.beginPath()
          ctx.arc(dotP.x, dotP.y, 3.5, 0, Math.PI * 2)
          ctx.fillStyle = '#ffffff'
          ctx.shadowColor = color
          ctx.shadowBlur = 18
          ctx.fill()
          ctx.shadowBlur = 0
        }
      }

      // ── City dots (glowing nodes) ──
      for (const [lat, lon] of CITIES) {
        const v = transform(ll2v(lat, lon, R), ry, rx)
        const p = proj(v, cx, cy, fov)
        if (!p.vis) continue
        // Outer glow
        ctx.beginPath()
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(0, 214, 143, 0.15)'
        ctx.fill()
        // Inner dot
        ctx.beginPath()
        ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(0, 230, 160, 0.9)'
        ctx.shadowColor = '#00D68F'
        ctx.shadowBlur = 12
        ctx.fill()
        ctx.shadowBlur = 0
      }

      // ── Token badges (hidden on mobile) ──
      if (!isMobile) {
        for (let i = 0; i < TOKENS.length; i++) {
          const tk = TOKENS[i]
          const orbR = R * 1.35
          const angle = time * 0.00015 * (0.5 + i * 0.12) + (i * Math.PI * 2) / TOKENS.length
          const yOff = Math.sin(time * 0.0007 + i * 0.8) * R * 0.08

          const raw: V3 = {
            x: Math.cos(angle) * orbR,
            y: ll2v(tk.lat, tk.lon, orbR).y + yOff,
            z: Math.sin(angle) * orbR,
          }
          const v = transform(raw, ry * 0.4, rx * 0.4)
          const p = proj(v, cx, cy, fov)
          if (!p.vis || p.s < 0.35) continue

          const sz = 14 * Math.max(p.s, 0.6)
          const alpha = Math.min(p.s * 0.7, 0.85)

          // Circle bg with glow
          ctx.globalAlpha = alpha
          ctx.shadowColor = tk.color
          ctx.shadowBlur = 8
          ctx.beginPath()
          ctx.arc(p.x, p.y, sz, 0, Math.PI * 2)
          ctx.fillStyle = tk.color + '18'
          ctx.fill()
          ctx.strokeStyle = tk.color + '50'
          ctx.lineWidth = 1.2
          ctx.stroke()
          ctx.shadowBlur = 0

          // Symbol
          ctx.fillStyle = tk.color
          ctx.font = `bold ${Math.round(sz * 0.9)}px var(--font-mono), monospace`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(tk.sym, p.x, p.y + 0.5)
          ctx.globalAlpha = 1
        }
      }

      frameRef.current = requestAnimationFrame(draw)
    }

    frameRef.current = requestAnimationFrame(draw)
    wrap.addEventListener('mousemove', handleMouse)

    return () => {
      running = false
      cancelAnimationFrame(frameRef.current)
      window.removeEventListener('resize', resize)
      wrap.removeEventListener('mousemove', handleMouse)
    }
  }, [handleMouse])

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%' }} />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  SVG ICONS
// ═══════════════════════════════════════════════════════════

function TwitterIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  )
}

function LinkedInIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  )
}
''
function DiscordIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03z" />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  )
}

function SparkleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(10,10,10,0.2)" strokeWidth="1.5">
      <path d="M12 2L13.5 8.5L20 10L13.5 11.5L12 18L10.5 11.5L4 10L10.5 8.5L12 2Z" />
      <path d="M19 14L19.75 16.25L22 17L19.75 17.75L19 20L18.25 17.75L16 17L18.25 16.25L19 14Z" />
    </svg>
  )
}

// ═══════════════════════════════════════════════════════════
//  FOOTER LINK COLUMNS
// ═══════════════════════════════════════════════════════════

const COLUMNS = [
  { title: 'Crypto Solutions', links: [
    { label: 'Crypto Payments',      href: '#how-it-works' },
    { label: 'Stablecoin Settlement', href: 'https://www.circle.com/usdc' },
    { label: 'Cross-Border Rails',   href: '#compliance' },
    { label: 'Institutional Custody', href: 'https://www.coinbase.com/prime' },
  ]},
  { title: 'Blockchain & Tech', links: [
    { label: 'Multi-Chain Interoperability', href: 'https://docs.base.org' },
    { label: 'Protocol Documentation',      href: 'https://docs.base.org/building-with-base/overview' },
    { label: 'Network Status',              href: 'https://status.base.org' },
    { label: 'Security Audits',             href: '#security' },
  ]},
  { title: 'Support & Resources', links: [
    { label: 'Contact Support', href: 'mailto:support@rsends.com' },
    { label: 'Help Center',     href: '#how-it-works' },
    { label: 'Integration Guides', href: 'https://docs.base.org/building-with-base/guides/overview' },
    { label: 'API Sandbox',     href: '#developers' },
  ]},
  { title: 'Company', links: [
    { label: 'About RSends', href: '#about' },
    { label: 'Global Reach', href: '#compliance' },
    { label: 'Careers (Web3)', href: 'https://www.linkedin.com/company/rsends/jobs' },
    { label: 'Press',         href: 'mailto:press@rsends.com' },
  ]},
]

const SOCIALS = [
  { label: 'Twitter',  icon: <TwitterIcon />,  url: 'https://twitter.com/RSendsHQ' },
  { label: 'LinkedIn', icon: <LinkedInIcon />, url: '#' },
  { label: 'Discord',  icon: <DiscordIcon />,  url: 'https://discord.gg/rsends' },
  { label: 'GitHub',   icon: <GitHubIcon />,   url: 'https://discord.gg/kbMVvA9U' },
]

// ═══════════════════════════════════════════════════════════
//  MAIN COMPONENT
// ═══════════════════════════════════════════════════════════

export default function FooterGlobe() {
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <footer className={styles.footer}>
      {/* ── Top gradient fade ── */}
      <div className={styles.topGradient} />

      {/* ── Links Bar ── */}
      <div className={styles.linksBackground}>
      <div className={styles.accentLine} />
      <div className={styles.linksBar}>
        <p className={styles.disclaimer}>
          *RSends&apos; global transaction throughput and compliance status based on composite network
          analysis and independent audits across multi-chain environments, 2026. Global average
          settlement times found to be up to 95% faster than legacy rails. Total Economic Impact of
          compliant crypto rails verified by composite study, Q2 2026.
        </p>

        <div className={styles.grid}>
          {COLUMNS.map(col => (
            <div key={col.title}>
              <div className={styles.colTitle}>{col.title}</div>
              {col.links.map(link => (
                <a
                  key={link.label}
                  href={link.href}
                  target={link.href.startsWith('http') || link.href.startsWith('mailto') ? '_blank' : undefined}
                  rel={link.href.startsWith('http') ? 'noopener noreferrer' : undefined}
                  className={styles.colLink}
                  onMouseEnter={() => setHovered(link.label)}
                  onMouseLeave={() => setHovered(null)}
                  style={{ color: hovered === link.label ? '#C8512C' : undefined, textDecoration: 'none', display: 'block' }}
                >
                  {link.label}
                </a>
              ))}
            </div>
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.bottomBar}>
          <div className={styles.bottomLeft}>
            <span className={styles.brandName}>RSends Inc.</span>
            <span>&copy; 2026</span>
            <span style={{ opacity: 0.3 }}>&middot;</span>
            <Link href="/docs/terms" className={styles.bottomTextLink} style={{ textDecoration: 'none', color: 'inherit' }}>Terms</Link>
            <span style={{ opacity: 0.3 }}>&middot;</span>
            <Link href="/docs/privacy" className={styles.bottomTextLink} style={{ textDecoration: 'none', color: 'inherit' }}>Privacy</Link>
            <span style={{ opacity: 0.3 }}>&middot;</span>
            <Link href="/docs/cookies" className={styles.bottomTextLink} style={{ textDecoration: 'none', color: 'inherit' }}>Cookies</Link>
            <span style={{ opacity: 0.3 }}>&middot;</span>
            <Link href="/docs/aml-kyc" className={styles.bottomTextLink} style={{ textDecoration: 'none', color: 'inherit' }}>AML/KYC</Link>
          </div>
          <div className={styles.socials}>
            {SOCIALS.map(s => (
              <a key={s.label} href={s.url} target="_blank" rel="noopener noreferrer"
                aria-label={s.label} className={styles.socialIcon}
              >{s.icon}</a>
            ))}
            <span style={{ marginLeft: 4 }}><SparkleIcon /></span>
          </div>
        </div>
      </div>
      </div>
    </footer>
  )
}
