<!-- components/horizon/HorizonSky.vue -->
<script setup lang="ts">
/**
 * HorizonSky — the living backdrop: a synaptic constellation in the sky band
 * (waking in sequence while Alice reasons) and light spores rising from the
 * horizon while she works. Declarative (props only). One rAF loop that
 * suspends once idle has fully faded and on document.hidden; a single static
 * draw under prefers-reduced-motion. Colors come from --hz-line-rgb and
 * --hz-sky-alpha (re-read on data-theme changes) — same discipline as
 * HorizonLine.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { HorizonSkyMode } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    mode?: HorizonSkyMode
    /** Line vertical position as a fraction of the scene height (spore origin). */
    lineQuota?: number
  }>(),
  { mode: 'idle', lineQuota: 0.58 }
)

interface SkyNode {
  x: number // fraction of width
  y: number // fraction of height (sky band)
  r: number
  phase: number
}
interface SkyEdge {
  a: number
  b: number
}
interface Spore {
  x: number
  speed: number
  phase: number
}

const NODE_COUNT = 20
const EDGE_NEIGHBORS = 2
const SPORE_COUNT = 6
/** Cross-fade speed (per second) between idle/awake/working intensities. */
const EASE_RATE = 0.8

const canvasRef = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let raf = 0
let running = false
let width = 0
let height = 0
let lineRgb = '232, 220, 200'
let baseAlpha = 0.1
/** 0 = asleep, 1 = fully awake (reasoning). Eases toward its target. */
let wake = 0
/** 0 = no spores, 1 = full working activity. Eases toward its target. */
let sporeLevel = 0
let lastNow = 0
let nodes: SkyNode[] = []
let edges: SkyEdge[] = []
let sporePool: Spore[] = []
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/** Deterministic PRNG: the constellation is stable across frames and mounts. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let z = Math.imul(a ^ (a >>> 15), 1 | a)
    z = (z + Math.imul(z ^ (z >>> 7), 61 | z)) ^ z
    return ((z ^ (z >>> 14)) >>> 0) / 4294967296
  }
}

function buildConstellation(): void {
  const rand = mulberry32(197)
  nodes = Array.from({ length: NODE_COUNT }, () => ({
    x: 0.06 + rand() * 0.88,
    y: 0.08 + rand() * 0.34, // sky band: above the central content
    r: 0.8 + rand() * 1.4,
    phase: rand() * Math.PI * 2
  }))
  edges = []
  nodes.forEach((n, i) => {
    const nearest = nodes
      .map((m, j) => ({ j, d: (n.x - m.x) ** 2 + (n.y - m.y) ** 2 }))
      .filter((e) => e.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, EDGE_NEIGHBORS)
    for (const e of nearest) {
      const dup = edges.some((ed) => (ed.a === e.j && ed.b === i) || (ed.a === i && ed.b === e.j))
      if (!dup) edges.push({ a: i, b: e.j })
    }
  })
  const srand = mulberry32(41)
  sporePool = Array.from({ length: SPORE_COUNT }, () => ({
    x: 0.15 + srand() * 0.7,
    speed: 0.05 + srand() * 0.05,
    phase: srand()
  }))
}

function readTheme(): void {
  const el = canvasRef.value
  if (!el) return
  const style = getComputedStyle(el)
  const rgb = style.getPropertyValue('--hz-line-rgb').trim()
  if (rgb) lineRgb = rgb
  const alpha = parseFloat(style.getPropertyValue('--hz-sky-alpha'))
  if (Number.isFinite(alpha)) baseAlpha = alpha
}

function resize(): void {
  const el = canvasRef.value
  if (!el || !el.parentElement) return
  const dpr = window.devicePixelRatio || 1
  width = el.parentElement.clientWidth
  height = el.parentElement.clientHeight
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
  if (reducedMotion) draw(performance.now())
}

function draw(now: number): void {
  if (!ctx || width === 0) return
  const t = now / 1000
  const dt = lastNow === 0 ? 0 : Math.min(0.1, (now - lastNow) / 1000)
  lastNow = now

  const wakeTarget = props.mode === 'thinking' ? 1 : 0
  const sporeTarget = props.mode === 'working' ? 1 : 0
  if (!reducedMotion) {
    wake += (wakeTarget - wake) * Math.min(1, EASE_RATE * dt * 3)
    sporeLevel += (sporeTarget - sporeLevel) * Math.min(1, EASE_RATE * dt * 3)
  } else {
    wake = wakeTarget
    sporeLevel = sporeTarget
  }

  ctx.clearRect(0, 0, width, height)

  /* ── constellation ── */
  ctx.save()
  ctx.lineWidth = 0.5
  for (const e of edges) {
    const a = nodes[e.a]
    const b = nodes[e.b]
    const surge = reducedMotion ? 0 : wake * (0.5 + Math.sin(t * 2 - (e.a + e.b) * 0.35) / 2) * 0.35
    ctx.strokeStyle = `rgba(${lineRgb}, ${baseAlpha * 0.6 + surge})`
    ctx.beginPath()
    ctx.moveTo(a.x * width, a.y * height)
    ctx.lineTo(b.x * width, b.y * height)
    ctx.stroke()
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]
    const twinkle = reducedMotion ? 0.5 : 0.5 + Math.sin(t * 0.9 + n.phase) / 2
    const surge = reducedMotion ? 0 : wake * (0.5 + Math.sin(t * 2.2 - i * 0.5) / 2)
    const a = baseAlpha * (0.6 + twinkle * 0.4) + surge * 0.6
    ctx.fillStyle = `rgba(${lineRgb}, ${Math.min(1, a)})`
    ctx.shadowColor = `rgba(${lineRgb}, 0.6)`
    ctx.shadowBlur = 4 + surge * 8
    ctx.beginPath()
    ctx.arc(n.x * width, n.y * height, n.r + surge * 0.8, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()

  /* ── spores rising from the horizon ── */
  if (sporeLevel > 0.01 && !reducedMotion) {
    ctx.save()
    const originY = props.lineQuota * height
    for (const s of sporePool) {
      const progress = (t * s.speed + s.phase) % 1
      const y = originY - progress * height * 0.28
      const a = sporeLevel * Math.sin(progress * Math.PI) * 0.7
      ctx.fillStyle = `rgba(${lineRgb}, ${a})`
      ctx.shadowColor = `rgba(${lineRgb}, 0.5)`
      ctx.shadowBlur = 3
      ctx.beginPath()
      ctx.arc(s.x * width, y, 1.1, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.restore()
  }

  // Fully settled and idle → suspend the loop (zero idle work).
  if (props.mode === 'idle' && wake < 0.01 && sporeLevel < 0.01 && !reducedMotion && running) {
    // One last faint frame is already painted; stop until inputs change.
    stop()
  }
}

function loop(now: number): void {
  if (!running) return
  draw(now)
  // draw() may have suspended the loop (idle settled): never re-schedule then,
  // or a later start() would end up with two concurrent rAF chains.
  if (!running) return
  raf = requestAnimationFrame(loop)
}

function start(): void {
  if (running || reducedMotion || !ctx) return
  running = true
  lastNow = 0
  raf = requestAnimationFrame(loop)
}

function stop(): void {
  running = false
  cancelAnimationFrame(raf)
}

function onVisibility(): void {
  if (document.hidden) stop()
  else start()
}

onMounted(() => {
  const el = canvasRef.value
  if (!el) return
  ctx = el.getContext('2d')
  buildConstellation()
  readTheme()
  resize()
  if (typeof ResizeObserver !== 'undefined' && el.parentElement) {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(el.parentElement)
  }
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      readTheme()
      if (reducedMotion) draw(performance.now())
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })
  }
  document.addEventListener('visibilitychange', onVisibility)
  if (reducedMotion) draw(performance.now())
  else start()
})

onBeforeUnmount(() => {
  stop()
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
})

// Mode changes must resume a suspended loop (or redraw statically).
watch(
  () => [props.mode, props.lineQuota],
  () => {
    if (reducedMotion) draw(performance.now())
    else start()
  }
)
</script>

<template>
  <div class="hz-sky" aria-hidden="true">
    <canvas ref="canvasRef" class="hz-sky__canvas" />
  </div>
</template>

<style scoped>
.hz-sky {
  position: absolute;
  inset: 0;
  z-index: 0; /* above the scene's grain, below the content zones (1-3) */
  pointer-events: none;
}

.hz-sky__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
