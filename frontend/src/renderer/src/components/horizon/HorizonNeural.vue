<!-- components/horizon/HorizonNeural.vue -->
<script setup lang="ts">
/**
 * HorizonNeural — the protagonist: a layered 3D neural network filling the
 * whole scene (spec 2026-07-14). Five discs of nodes along the horizontal
 * axis, perspective projection, slow spin around the layer axis, damped
 * cursor parallax. Signals are causal: light packets travel edges and nodes
 * flash on arrival; propagation is free (random hops) — only the endpoints
 * are semantic (voice enters disc 0, speech exits the last disc).
 *
 * Declarative (props only). One rAF loop with a full suspension pattern:
 * explicit redraws on resize/theme while suspended, double running guard
 * in loop(), start() never arms while hidden. In quiet the loop stops once
 * settled; a timer wakes it every
 * ~4 s for a single wandering "dream" signal, then it re-suspends.
 * Colors come from --hz-line-rgb / --hz-sky-alpha (re-read on data-theme).
 * The state microlabel and the plan annotation are DOM overlays tracked on
 * projected nodes (crisp text, readable by screen readers; canvas stays
 * aria-hidden).
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { HorizonState } from '../../composables/horizon/horizonScene'
import {
  DISC_COUNT,
  buildNeuralGraph,
  projectNode,
  depthNorm,
  anyHop,
  routeView,
  mulberry32,
  type Hop,
  type NeuralGraph,
  type ProjectedNode
} from '../../composables/horizon/neuralGraph'

const props = withDefaults(
  defineProps<{
    state: HorizonState
    /** Mic level 0–1 (membrane on disc 0). */
    audioLevel?: number
    /** TTS is speaking (syllabic cadence + rings on the last disc). */
    speaking?: boolean
    /** Plan size; 0 = no route drawn. */
    planTotal?: number
    /** Active plan step (planView.activeIndex). */
    planActiveIndex?: number
    /** Completed plan steps (planView.completed). */
    planCompleted?: number
    /** Italic annotation beside the active ganglion ('' = hidden). */
    planStepLabel?: string
    /** State microlabel anchored to the polar node ('' = hidden). */
    label?: string
    /** Dim the whole net (disconnected / dialog behind). */
    dimmed?: boolean
  }>(),
  {
    audioLevel: 0,
    speaking: false,
    planTotal: 0,
    planActiveIndex: -1,
    planCompleted: 0,
    planStepLabel: '',
    label: '',
    dimmed: false
  }
)

/* ── constants ── */
const SEED = 197
const MAX_TRAVELERS = 48
const DREAM_EVERY_MS = 4200
const DREAM_HOPS = 4
const SWEEP_EVERY = 2.1
/** Parallax swing amplitudes (rad). */
const SWING_Y = 0.3
const TILT_X = 0.22
/** Cross-fade speed of the state intensities (per second). */
const EASE_RATE = 3

interface Traveler {
  ek: number
  rev: boolean
  f: number
  speed: number
  strength: number
  hops: number
  kind: 'free' | 'dream' | 'voice' | 'flow'
}
interface Ring {
  ni: number
  f: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
const labelRef = ref<HTMLSpanElement | null>(null)
const annotationRef = ref<HTMLSpanElement | null>(null)

const graph: NeuralGraph = buildNeuralGraph(SEED)
/** Runtime randomness (choreographies), separate from the layout seed. */
const rand = mulberry32(SEED * 7 + 1)

let ctx: CanvasRenderingContext2D | null = null
let raf = 0
let running = false
let width = 0
let height = 0
let lineRgb = '232, 220, 200'
let baseAlpha = 0.1
let lastNow = 0

/* camera */
let spin = 0
let spinVel = 0
let mx = 0
let my = 0
let targetMx = 0
let targetMy = 0

/* state cross-fade intensities */
const intens: Record<HorizonState, number> = {
  quiet: 1,
  listening: 0,
  thinking: 0,
  responding: 0,
  working: 0
}

/* simulation */
let travelers: Traveler[] = []
const flash = new Float32Array(graph.nodes.length)
let rings: Ring[] = []
let levelSmooth = 0
let inputAccum = 0
let humAccum = 0
let flowAccum = 0
let sweepClock = 0
let sweepMode: 'forward' | 'backward' | 'center' = 'forward'
let sweepDim = 0.9
let sweepCount = 0
let dreamTimer: ReturnType<typeof setTimeout> | null = null

/* route easing: the displayed active ganglion glides (the old sparkX pattern) */
let routeEase = 0
let routeShown = 0
let lastPlanTotal = 0

let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
const pointerFine =
  typeof window !== 'undefined' && window.matchMedia?.('(pointer: fine)').matches === true

/* ── helpers ── */

/** Exponential damping (frame-rate independent). */
function damp(x: number, target: number, lambda: number, dt: number): number {
  return x + (target - x) * (1 - Math.exp(-lambda * dt))
}

/** Speech-like cadence for the speaking choreography (phrases + syllables). */
function speechCadence(t: number): number {
  const phrase = 0.5 + 0.5 * Math.sin(t * 0.42 + 2)
  const syll = 0.5 + 0.28 * Math.sin(t * 3.6) + 0.22 * Math.sin(t * 8.1 + 0.7)
  return Math.max(0, Math.min(1, phrase > 0.35 ? syll : 0.04))
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
  // The loop may be suspended (quiet settled): repaint explicitly.
  if (reducedMotion || !running) draw(performance.now())
}

/* ── simulation ── */

/**
 * Spawn a traveler out of `from`. Free flow by default (anyHop); with
 * `forwardBias` it prefers (70%) an edge toward the next disc when one
 * exists — the responding gather toward the output disc.
 */
function spawnHop(
  from: number,
  strength: number,
  kind: Traveler['kind'],
  speed?: number,
  forwardBias = false
): boolean {
  if (travelers.length >= MAX_TRAVELERS) return false
  let hop: Hop | null = null
  if (forwardBias && rand() < 0.7) {
    const fwd = graph.nodes[from].edges.filter((ek) => {
      const e = graph.edges[ek]
      const to = e.a === from ? e.b : e.a
      return graph.nodes[to].col > graph.nodes[from].col
    })
    if (fwd.length > 0) {
      const ek = fwd[Math.floor(rand() * fwd.length)]
      const e = graph.edges[ek]
      hop = { ek, rev: e.b === from, to: e.a === from ? e.b : e.a }
    }
  }
  hop ??= anyHop(graph, from, rand)
  if (!hop) return false
  travelers.push({
    ek: hop.ek,
    rev: hop.rev,
    f: 0,
    speed: speed ?? 0.9 + rand() * 0.4,
    strength,
    hops: 0,
    kind
  })
  return true
}

function stepSim(dt: number, t: number): void {
  for (let i = 0; i < flash.length; i++) flash[i] = Math.max(0, flash[i] - dt * 1.7)
  rings = rings.filter((r) => (r.f += dt * 0.9) < 1)

  // Clamp: a NaN/out-of-range level would poison the smoother permanently.
  const safeLevel = Number.isFinite(props.audioLevel)
    ? Math.min(1, Math.max(0, props.audioLevel))
    : 0
  const levelTarget = props.state === 'listening' ? Math.max(safeLevel, 0.06) : 0
  levelSmooth += (levelTarget - levelSmooth) * Math.min(1, dt * 8)

  /* listening — the voice pushes activations in from disc 0 */
  if (props.state === 'listening') {
    inputAccum += levelSmooth * 5.5 * dt
    while (inputAccum >= 1) {
      inputAccum -= 1
      const col0 = graph.byCol[0]
      const ni = col0[Math.floor(rand() * col0.length)]
      flash[ni] = Math.max(flash[ni], 0.5 + levelSmooth * 0.5)
      spawnHop(ni, 0.45 + levelSmooth * 0.4, 'voice')
    }
  }

  /* thinking — coherent sweeps, random direction, every third an echo */
  if (props.state === 'thinking') {
    sweepClock += dt
    if (sweepClock > SWEEP_EVERY) {
      sweepClock = 0
      sweepCount++
      const r = rand()
      sweepMode = r < 1 / 3 ? 'forward' : r < 2 / 3 ? 'backward' : 'center'
      sweepDim = sweepCount % 3 === 2 ? 0.45 : 0.9
    }
  }

  /* working — low hum of short free signals */
  if (props.state === 'working') {
    humAccum += dt * 1.1
    while (humAccum >= 1) {
      humAccum -= 1
      const ni = Math.floor(rand() * graph.nodes.length)
      flash[ni] = Math.max(flash[ni], 0.3)
      spawnHop(ni, 0.3, 'free')
    }
  }

  /* responding — signals gather toward the output disc; cadence rings when speaking */
  if (props.state === 'responding') {
    const drive = props.speaking ? speechCadence(t) : 0.35
    flowAccum += (0.8 + drive * 2.2) * dt
    while (flowAccum >= 1) {
      flowAccum -= 1
      const ni = Math.floor(rand() * graph.nodes.length)
      spawnHop(ni, 0.4 + drive * 0.3, 'flow', 1.1, true)
    }
    if (props.speaking && drive > 0.72 && rings.length < 6 && rand() < dt * 9) {
      const out = graph.byCol[DISC_COUNT - 1]
      const ni = out[Math.floor(rand() * out.length)]
      rings.push({ ni, f: 0 })
      flash[ni] = Math.max(flash[ni], 0.8)
    }
  }

  /* advance travelers; arrivals flash the node and may keep going */
  const arrived: Traveler[] = []
  travelers = travelers.filter((tr) => {
    tr.f += tr.speed * dt
    if (tr.f < 1) return true
    arrived.push(tr)
    return false
  })
  for (const tr of arrived) {
    const e = graph.edges[tr.ek]
    const ni = tr.rev ? e.a : e.b
    flash[ni] = Math.max(flash[ni], tr.strength)
    let go = false
    if (tr.kind === 'dream') go = tr.hops < DREAM_HOPS
    else if (tr.kind === 'voice') go = tr.hops < 2 && rand() < 0.7
    else if (tr.kind === 'flow') go = graph.nodes[ni].col < DISC_COUNT - 1
    if (go) {
      const spawned = spawnHop(
        ni,
        tr.strength * (tr.kind === 'dream' ? 1 : 0.85),
        tr.kind,
        tr.speed,
        tr.kind === 'flow'
      )
      if (spawned) travelers[travelers.length - 1].hops = tr.hops + 1
    }
  }
}

/* ── camera ── */
function updateCamera(dt: number): void {
  const targetVel =
    props.state === 'working'
      ? 0
      : props.state === 'thinking'
        ? 0.3
        : props.state === 'quiet'
          ? 0.1
          : 0.16
  spinVel = damp(spinVel, targetVel, 2.5, dt)
  spin += spinVel * dt
  mx = damp(mx, targetMx, 6, dt)
  my = damp(my, targetMy, 6, dt)
}

/* thinking wavefront glow per disc */
function colGlow(c: number): number {
  if (intens.thinking < 0.02) return 0
  const prog = Math.min(1, sweepClock / (SWEEP_EVERY * 0.6))
  const strength = Math.sin(prog * Math.PI * 0.9 + 0.1) * sweepDim * intens.thinking
  const mid = (DISC_COUNT - 1) / 2
  let d: number
  if (sweepMode === 'forward') d = Math.abs(c - (DISC_COUNT - 1) * prog)
  else if (sweepMode === 'backward') d = Math.abs(c - (DISC_COUNT - 1) * (1 - prog))
  else d = Math.abs(Math.abs(c - mid) - mid * prog)
  return Math.max(0, 1 - d * 0.9) * strength
}

/** Quiet settle check: cross-fades done, sim empty, parallax converged. */
function isSettled(): boolean {
  if (intens.listening + intens.thinking + intens.responding + intens.working > 0.02) return false
  if (travelers.length > 0 || rings.length > 0) return false
  if (Math.abs(mx - targetMx) + Math.abs(my - targetMy) > 0.002) return false
  for (let i = 0; i < flash.length; i++) if (flash[i] > 0.01) return false
  return true
}

/* ── overlays (DOM label + annotation tracked on projected nodes) ── */
function positionOverlays(P: ProjectedNode[]): void {
  const lab = labelRef.value
  if (lab) {
    const p = P[graph.polar]
    lab.style.transform = `translate(${Math.round(p.sx + 14)}px, ${Math.round(p.sy - 30)}px)`
  }
  const ann = annotationRef.value
  if (ann && props.planTotal > 0) {
    const p = P[graph.plan[routeShown]]
    const flip = p.sx > width / 2
    ann.style.transform =
      `translate(${Math.round(p.sx + (flip ? -12 : 12))}px, ${Math.round(p.sy - 26)}px)` +
      (flip ? ' translateX(-100%)' : '')
  }
}

/* ── draw ── */
function draw(now: number): void {
  if (!ctx || width === 0) return
  const t = now / 1000
  const dt = lastNow === 0 ? 0 : Math.max(0, Math.min(0.1, (now - lastNow) / 1000))
  lastNow = now

  if (!reducedMotion) {
    for (const s of Object.keys(intens) as HorizonState[]) {
      const target = props.state === s ? 1 : 0
      intens[s] += (target - intens[s]) * Math.min(1, EASE_RATE * dt)
    }
    updateCamera(dt)
    stepSim(dt, t)
  } else {
    for (const s of Object.keys(intens) as HorizonState[]) intens[s] = props.state === s ? 1 : 0
    spin = 0
    mx = 0
    my = 0
    travelers = []
    rings = []
    levelSmooth = props.state === 'listening' ? 0.3 : 0
  }

  const c = ctx
  c.clearRect(0, 0, width, height)
  c.save()
  c.globalAlpha = props.dimmed ? 0.35 : 1

  const breathe = reducedMotion ? 0.5 : 0.5 + Math.sin(t * 0.5) / 2
  const focusDim = 1 - intens.working * 0.45
  const base =
    (baseAlpha * (0.75 + breathe * 0.2) +
      intens.listening * levelSmooth * 0.05 +
      (intens.thinking + intens.responding) * 0.03) *
    focusDim

  const rotX = spin + my * TILT_X
  const rotY = mx * SWING_Y
  const vp = { w: width, h: height }

  // membrane: disc-0 nodes vibrate radially with the voice waveform
  const membR = (i: number): number => {
    const n = graph.nodes[i]
    if (n.col !== 0 || intens.listening < 0.02 || reducedMotion) return 1
    return (
      1 +
      intens.listening *
        levelSmooth *
        (Math.sin(n.phase * 5 + t * 9) * 0.16 + Math.sin(n.phase * 11 - t * 13) * 0.1)
    )
  }

  const P = graph.nodes.map((n, i) => {
    const m = membR(i)
    return projectNode({ x: n.x, y: n.y * m, z: n.z * m }, rotX, rotY, vp)
  })

  /* edges — brighter where a traveler runs or the thinking wave passes */
  const edgeGlow = new Float32Array(graph.edges.length)
  for (const tr of travelers) edgeGlow[tr.ek] = Math.max(edgeGlow[tr.ek], tr.strength)
  c.lineWidth = 0.6
  graph.edges.forEach((e, k) => {
    const a = P[e.a]
    const b = P[e.b]
    const dn = (depthNorm(a.scale) + depthNorm(b.scale)) / 2
    const wave = Math.min(colGlow(graph.nodes[e.a].col), colGlow(graph.nodes[e.b].col)) * 0.35
    c.strokeStyle = `rgba(${lineRgb}, ${base * (0.35 + dn * 0.65) + edgeGlow[k] * 0.26 + wave})`
    c.beginPath()
    c.moveTo(a.sx, a.sy)
    c.lineTo(b.sx, b.sy)
    c.stroke()
  })

  /* travelers — light packets gliding the edges (3D-interpolated) */
  for (const tr of travelers) {
    const e = graph.edges[tr.ek]
    const ai = tr.rev ? e.b : e.a
    const bi = tr.rev ? e.a : e.b
    const na = graph.nodes[ai]
    const nb = graph.nodes[bi]
    const p = projectNode(
      {
        x: na.x + (nb.x - na.x) * tr.f,
        y: na.y + (nb.y - na.y) * tr.f,
        z: na.z + (nb.z - na.z) * tr.f
      },
      rotX,
      rotY,
      vp
    )
    const al = tr.strength * Math.sin(tr.f * Math.PI) * (0.45 + depthNorm(p.scale) * 0.55)
    const rr = 6 * p.scale
    const rg = c.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, rr)
    rg.addColorStop(0, `rgba(${lineRgb}, ${0.9 * al})`)
    rg.addColorStop(1, `rgba(${lineRgb}, 0)`)
    c.fillStyle = rg
    c.fillRect(p.sx - rr, p.sy - rr, rr * 2, rr * 2)
  }

  /* speaking rings on the output disc */
  for (const r of rings) {
    const p = P[r.ni]
    c.strokeStyle = `rgba(${lineRgb}, ${(1 - r.f) * 0.5 * intens.responding})`
    c.lineWidth = 1.2
    c.beginPath()
    c.arc(p.sx, p.sy, (4 + r.f * 26) * p.scale, 0, Math.PI * 2)
    c.stroke()
  }
  c.lineWidth = 0.6

  /* nodes back-to-front */
  const cad = props.speaking && !reducedMotion ? speechCadence(t) : 0
  const order = graph.nodes.map((_, i) => i).sort((a, b) => P[a].z - P[b].z)
  for (const i of order) {
    const n = graph.nodes[i]
    const p = P[i]
    const dn = depthNorm(p.scale)
    const tw = reducedMotion ? 0.5 : 0.5 + Math.sin(t * 0.8 + n.phase) / 2
    let a = base * (2.4 + tw * 1.2) * (0.35 + dn * 0.65) + flash[i] * 0.85 + colGlow(n.col) * 0.5
    let r = n.size * (1.1 + dn * 1.1) + flash[i] * 1.7
    if (n.col === 0) {
      a += intens.listening * levelSmooth * 0.5
      r += intens.listening * levelSmooth * 1.2
    }
    if (n.col === DISC_COUNT - 1) {
      a += intens.responding * cad * 0.55
      r += intens.responding * cad * 1.1
    }
    c.fillStyle = `rgba(${lineRgb}, ${Math.min(1, a)})`
    c.shadowColor = `rgba(${lineRgb}, 0.6)`
    c.shadowBlur = (3 + flash[i] * 10 + colGlow(n.col) * 6) * p.scale
    c.beginPath()
    c.arc(p.sx, p.sy, Math.max(0.4, r * p.scale), 0, Math.PI * 2)
    c.fill()
    c.shadowBlur = 0
  }

  /* working — the route takes the stage (spin is damped to rest by updateCamera) */
  if (intens.working > 0.02 && props.planTotal > 0) {
    const route = routeView(props.planActiveIndex, props.planCompleted, props.planTotal)
    // A NEW plan snaps; within-plan motion (including mid-run growth) glides.
    if (lastPlanTotal === 0 || reducedMotion) routeEase = route.active
    else routeEase = damp(routeEase, route.active, 4, dt)
    routeShown = Math.max(0, Math.min(DISC_COUNT - 1, Math.round(routeEase)))
    const shownDone = Math.min(route.done, routeShown)
    const pts = graph.plan.map((ni) => P[ni])
    c.save()
    c.globalAlpha = (props.dimmed ? 0.35 : 1) * intens.working
    for (let k = 0; k < DISC_COUNT - 1; k++) {
      const lit = k < routeShown
      c.strokeStyle = `rgba(${lineRgb}, ${lit ? 0.6 : 0.2})`
      c.lineWidth = 1
      c.setLineDash(lit ? [] : [1, 3])
      c.beginPath()
      c.moveTo(pts[k].sx, pts[k].sy)
      c.lineTo(pts[k + 1].sx, pts[k + 1].sy)
      c.stroke()
    }
    c.setLineDash([])
    if (routeShown > 0 && !reducedMotion) {
      const k = routeShown - 1
      const f = (t * 0.7) % 1
      const x = pts[k].sx + (pts[k + 1].sx - pts[k].sx) * f
      const y = pts[k].sy + (pts[k + 1].sy - pts[k].sy) * f
      c.fillStyle = `rgba(${lineRgb}, 0.9)`
      c.beginPath()
      c.arc(x, y, 1.8, 0, Math.PI * 2)
      c.fill()
    }
    pts.forEach((p, k) => {
      const done = k < shownDone
      const active = k === routeShown
      const pulse = active && !reducedMotion ? 0.75 + Math.sin(t * 3) * 0.25 : 1
      c.strokeStyle = `rgba(${lineRgb}, ${active ? 1 : done ? 0.85 : 0.35})`
      c.lineWidth = active ? 1.4 : 1
      c.beginPath()
      c.arc(p.sx, p.sy, (active ? 6.5 : 5) * p.scale, 0, Math.PI * 2)
      c.stroke()
      if (done) {
        c.fillStyle = `rgba(${lineRgb}, 0.9)`
        c.beginPath()
        c.arc(p.sx, p.sy, 1.8 * p.scale, 0, Math.PI * 2)
        c.fill()
      }
      if (active) {
        c.fillStyle = `rgba(${lineRgb}, ${0.9 * pulse})`
        c.beginPath()
        c.arc(p.sx, p.sy, 2.2 * p.scale, 0, Math.PI * 2)
        c.fill()
      }
    })
    c.restore()
  }

  c.restore()
  positionOverlays(P)
  lastPlanTotal = props.planTotal

  // Quiet fully settled → suspend; the dream timer re-arms the loop.
  if (!reducedMotion && running && props.state === 'quiet' && isSettled()) {
    stop()
    armDream()
  }
}

/* ── loop / suspension ── */
function loop(now: number): void {
  if (!running) return
  draw(now)
  // draw() may have suspended the loop (quiet settled): never re-schedule
  // then, or a later start() would end up with two concurrent rAF chains.
  if (!running) return
  raf = requestAnimationFrame(loop)
}

function start(): void {
  if (document.hidden) return
  if (running || reducedMotion || !ctx) return
  running = true
  lastNow = 0
  raf = requestAnimationFrame(loop)
}

function stop(): void {
  running = false
  cancelAnimationFrame(raf)
}

function clearDream(): void {
  if (dreamTimer) {
    clearTimeout(dreamTimer)
    dreamTimer = null
  }
}

/** While suspended in quiet, wake up every ~4 s for one wandering dream. */
function armDream(): void {
  clearDream()
  dreamTimer = setTimeout(() => {
    dreamTimer = null
    if (props.state !== 'quiet' || reducedMotion || document.hidden) return
    const ni = Math.floor(rand() * graph.nodes.length)
    flash[ni] = 0.4
    spawnHop(ni, 0.38, 'dream', 0.8)
    start()
  }, DREAM_EVERY_MS)
}

function onVisibility(): void {
  if (document.hidden) {
    stop()
    clearDream()
  } else {
    start()
  }
}

/* ── parallax (fine pointers only; reduced-motion disables it) ── */
function onPointerMove(e: MouseEvent): void {
  targetMx = (e.clientX / window.innerWidth) * 2 - 1
  targetMy = (e.clientY / window.innerHeight) * 2 - 1
  // A cursor move must wake a suspended loop (it re-settles on its own).
  if (!running && !document.hidden) start()
}

function onPointerOut(e: MouseEvent): void {
  if (e.relatedTarget === null) {
    targetMx = 0
    targetMy = 0
    if (!running && !document.hidden) start()
  }
}

/* ── lifecycle ── */
onMounted(() => {
  const el = canvasRef.value
  if (!el) return
  ctx = el.getContext('2d')
  readTheme()
  resize()
  if (typeof ResizeObserver !== 'undefined' && el.parentElement) {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(el.parentElement)
  }
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      readTheme()
      // The loop may be suspended: repaint explicitly.
      if (reducedMotion || !running) draw(performance.now())
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })
  }
  document.addEventListener('visibilitychange', onVisibility)
  if (pointerFine && !reducedMotion) {
    window.addEventListener('mousemove', onPointerMove, { passive: true })
    window.addEventListener('mouseout', onPointerOut, { passive: true })
  }
  if (reducedMotion) draw(performance.now())
  else start()
})

onBeforeUnmount(() => {
  stop()
  clearDream()
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('mousemove', onPointerMove)
  window.removeEventListener('mouseout', onPointerOut)
})

// Any prop change must resume a suspended loop (or redraw statically).
watch(
  () => [
    props.state,
    props.audioLevel,
    props.speaking,
    props.planTotal,
    props.planActiveIndex,
    props.planCompleted,
    props.planStepLabel,
    props.label,
    props.dimmed
  ],
  () => {
    clearDream()
    if (reducedMotion) draw(performance.now())
    else start()
  },
  { flush: 'post' }
)
</script>

<template>
  <div class="hz-neural" :class="{ 'hz-neural--dimmed': dimmed }">
    <canvas ref="canvasRef" class="hz-neural__canvas" aria-hidden="true" />
    <Transition name="hz-neural-fade">
      <span v-if="label" :key="label" ref="labelRef" class="hz-neural__label">{{ label }}</span>
    </Transition>
    <Transition name="hz-neural-fade">
      <span
        v-if="state === 'working' && planTotal > 0 && planStepLabel"
        ref="annotationRef"
        class="hz-neural__annotation"
        >{{ planStepLabel }}</span
      >
    </Transition>
  </div>
</template>

<style scoped>
.hz-neural {
  position: absolute;
  inset: 0;
  z-index: 0; /* above the scene's grain, below the content zones */
  pointer-events: none;
}

.hz-neural__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

/* State microlabel: cartographic annotation tracked on the polar node. */
.hz-neural__label {
  position: absolute;
  top: 0;
  left: 0;
  padding-left: 14px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  white-space: nowrap;
  user-select: none;
  will-change: transform;
}

.hz-neural__label::before {
  content: '';
  position: absolute;
  left: 0;
  bottom: -3px;
  width: 12px;
  height: 1px;
  background: currentColor;
  opacity: 0.5;
  transform: rotate(-35deg);
  transform-origin: left bottom;
}

/* Plan-step annotation beside the active ganglion. */
.hz-neural__annotation {
  position: absolute;
  top: 0;
  left: 0;
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: 13px;
  color: var(--hz-ink);
  white-space: nowrap;
  user-select: none;
  will-change: transform;
}

.hz-neural__label,
.hz-neural__annotation {
  transition: opacity var(--hz-fade) ease;
}

.hz-neural--dimmed .hz-neural__label,
.hz-neural--dimmed .hz-neural__annotation {
  opacity: 0.35;
}

.hz-neural-fade-enter-active,
.hz-neural-fade-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-neural-fade-enter-from,
.hz-neural-fade-leave-to {
  opacity: 0;
}
</style>
