# Horizon «Rete Neurale» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare la linea d'orizzonte e promuovere la rete neurale a protagonista: una rete 3D «a strati» a tutta scena (5 dischi di nodi, prospettiva, parallasse del cursore, segnali causali a flusso randomico) che assorbe i cinque lavori della linea.

**Architecture:** Un modulo puro `neuralGraph.ts` (grafo deterministico, proiezione 3D, hop randomico, mapping rotta — node env, unit-testato) + un componente canvas dichiarativo `HorizonNeural.vue` (simulazione, coreografie per stato, camera, sospensione col pattern di HorizonSky, label/annotazione come overlay DOM tracciati). `HorizonLine.vue` e `HorizonSky.vue` si eliminano; il brain perde solo i modi linea/sky; il zoning a quota di `HorizonScene` resta.

**Tech Stack:** Vue 3 `<script setup lang="ts">`, canvas 2D, vitest (node env), token `--hz-*` dual-theme.

**Spec:** `docs/superpowers/specs/2026-07-14-horizon-neural-design.md` (approvata). Mockup di riferimento: `.superpowers/brainstorm/203-1784049699/content/stati-3d.html` + correzione utente «flusso randomico».

**Convenzioni vincolanti** (handoff 2026-07-14): commit single-line convenzionali SENZA Co-Authored-By; gates da `frontend/` in PowerShell 5.1 (`;` non `&&`): `npx vitest run; npm run typecheck; npm run lint` — lint a ZERO warning (`npx eslint --fix` per i nit prettier, verificando che il diff sia formatting-only); solo token con fallback, mai letterali; `prefers-reduced-motion` su ogni animazione continua.

---

### Task 1: `neuralGraph.ts` — modulo puro (grafo 3D, proiezione, hop, rotta)

**Files:**
- Create: `frontend/src/renderer/src/composables/horizon/neuralGraph.ts`
- Test: `frontend/src/renderer/src/composables/horizon/neuralGraph.spec.ts`

- [ ] **Step 1: Write the failing tests**

Contenuto completo di `neuralGraph.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  DISC_COUNT,
  FOV,
  buildNeuralGraph,
  projectNode,
  depthNorm,
  anyHop,
  routeView,
  mulberry32
} from './neuralGraph'

describe('buildNeuralGraph', () => {
  it('is deterministic for the same seed', () => {
    const a = buildNeuralGraph(197)
    const b = buildNeuralGraph(197)
    expect(a.nodes).toEqual(b.nodes)
    expect(a.edges).toEqual(b.edges)
  })

  it('changes with the seed', () => {
    const a = buildNeuralGraph(197)
    const b = buildNeuralGraph(198)
    expect(a.nodes).not.toEqual(b.nodes)
  })

  it('lays out five discs along the x axis', () => {
    const g = buildNeuralGraph(197)
    expect(g.byCol).toHaveLength(DISC_COUNT)
    g.byCol.forEach((col, c) => {
      expect(col.length).toBeGreaterThan(0)
      const lx = -1 + (c / (DISC_COUNT - 1)) * 2
      for (const i of col) {
        expect(g.nodes[i].col).toBe(c)
        expect(Math.abs(g.nodes[i].x - lx)).toBeLessThanOrEqual(0.07 + 1e-9)
      }
    })
  })

  it('connects only adjacent discs, deduplicated, degree >= 1', () => {
    const g = buildNeuralGraph(197)
    const seen = new Set<string>()
    for (const e of g.edges) {
      expect(Math.abs(g.nodes[e.a].col - g.nodes[e.b].col)).toBe(1)
      const key = `${Math.min(e.a, e.b)}-${Math.max(e.a, e.b)}`
      expect(seen.has(key)).toBe(false)
      seen.add(key)
    }
    g.nodes.forEach((n) => expect(n.edges.length).toBeGreaterThanOrEqual(1))
  })

  it('indexes incident edges consistently', () => {
    const g = buildNeuralGraph(197)
    g.nodes.forEach((n, i) => {
      for (const ek of n.edges) {
        const e = g.edges[ek]
        expect(e.a === i || e.b === i).toBe(true)
      }
    })
  })

  it('picks one route ganglion per disc and a polar anchor on the last disc', () => {
    const g = buildNeuralGraph(197)
    expect(g.plan).toHaveLength(DISC_COUNT)
    g.plan.forEach((ni, c) => expect(g.nodes[ni].col).toBe(c))
    expect(g.nodes[g.polar].col).toBe(DISC_COUNT - 1)
  })
})

describe('projectNode', () => {
  const vp = { w: 1000, h: 500 }

  it('projects the origin to the viewport center at scale 1', () => {
    const p = projectNode({ x: 0, y: 0, z: 0 }, 0, 0, vp)
    expect(p.sx).toBeCloseTo(500)
    expect(p.sy).toBeCloseTo(250)
    expect(p.scale).toBeCloseTo(1)
  })

  it('scales up near nodes and down far nodes', () => {
    const near = projectNode({ x: 0, y: 0, z: 0.8 }, 0, 0, vp)
    const far = projectNode({ x: 0, y: 0, z: -0.8 }, 0, 0, vp)
    expect(near.scale).toBeGreaterThan(1)
    expect(far.scale).toBeLessThan(1)
  })

  it('spin around the layer axis keeps a node on its side of the screen', () => {
    const p0 = projectNode({ x: 0.7, y: 0.3, z: 0.1 }, 0, 0, vp)
    const p1 = projectNode({ x: 0.7, y: 0.3, z: 0.1 }, 1.3, 0, vp)
    expect(Math.sign(p1.sx - 500)).toBe(Math.sign(p0.sx - 500))
  })

  it('swing around the vertical axis moves x', () => {
    const p0 = projectNode({ x: 0.7, y: 0, z: 0 }, 0, 0, vp)
    const p1 = projectNode({ x: 0.7, y: 0, z: 0 }, 0, 0.3, vp)
    expect(Math.abs(p1.sx - p0.sx)).toBeGreaterThan(1)
  })
})

describe('depthNorm', () => {
  it('normalizes the FOV scale range to 0..1', () => {
    expect(depthNorm(FOV / (FOV + 1))).toBeCloseTo(0)
    expect(depthNorm(FOV / (FOV - 1))).toBeCloseTo(1)
    expect(depthNorm(1)).toBeGreaterThan(0)
    expect(depthNorm(1)).toBeLessThan(1)
  })

  it('clamps out-of-range scales', () => {
    expect(depthNorm(0)).toBe(0)
    expect(depthNorm(99)).toBe(1)
  })
})

describe('anyHop', () => {
  it('returns hops only along incident edges of the source node', () => {
    const g = buildNeuralGraph(197)
    const rand = mulberry32(1)
    for (let i = 0; i < g.nodes.length; i++) {
      const hop = anyHop(g, i, rand)
      expect(hop).not.toBeNull()
      const e = g.edges[hop!.ek]
      expect(e.a === i || e.b === i).toBe(true)
      expect(hop!.to).toBe(e.a === i ? e.b : e.a)
      expect(hop!.rev).toBe(e.b === i)
    }
  })
})

describe('routeView', () => {
  it('maps an empty plan to no route', () => {
    expect(routeView(0, 0, 0)).toEqual({ active: -1, done: 0 })
  })

  it('maps a 5-step plan 1:1', () => {
    expect(routeView(0, 0, 5)).toEqual({ active: 0, done: 0 })
    expect(routeView(2, 2, 5)).toEqual({ active: 2, done: 2 })
    expect(routeView(4, 4, 5)).toEqual({ active: 4, done: 4 })
  })

  it('scales longer plans proportionally', () => {
    expect(routeView(3, 3, 8)).toEqual({ active: 2, done: 1 })
    expect(routeView(7, 7, 8)).toEqual({ active: 4, done: 4 })
  })

  it('handles single-step and fully completed plans', () => {
    expect(routeView(0, 0, 1)).toEqual({ active: 0, done: 0 })
    expect(routeView(0, 1, 1)).toEqual({ active: 0, done: 5 })
    expect(routeView(4, 5, 5)).toEqual({ active: 4, done: 5 })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (da `frontend/`): `npx vitest run src/renderer/src/composables/horizon/neuralGraph.spec.ts`
Expected: FAIL — `Cannot find module './neuralGraph'` (o equivalente).

- [ ] **Step 3: Write the implementation**

Contenuto completo di `neuralGraph.ts`:

```ts
/**
 * neuralGraph.ts — Pure 3D geometry for the Horizon neural network.
 *
 * Five discs of nodes along the horizontal axis (the layered-network
 * silhouette), perspective projection with a camera on +z, free random
 * hops along edges (spec 2026-07-14: propagation is NOT constrained to
 * the input→output direction). No Vue/DOM imports: fully unit-testable
 * in the node environment, same discipline as horizonScene.ts.
 */

export interface NeuralNode {
  /** Layer-axis position (−1..1) with a small jitter. */
  x: number
  y: number
  z: number
  /** Disc index (0 = input/membrane, DISC_COUNT−1 = output/speech). */
  col: number
  /** Size weight 0.6..1.5. */
  size: number
  /** Per-node breathing phase. */
  phase: number
  /** Incident edge indices (filled by buildNeuralGraph). */
  edges: number[]
}

/** Undirected edge between node indices. */
export interface NeuralEdge {
  a: number
  b: number
}

export interface NeuralGraph {
  nodes: NeuralNode[]
  edges: NeuralEdge[]
  /** Node indices grouped by disc. */
  byCol: number[][]
  /** Route ganglia: per disc, the node nearest the disc center. */
  plan: number[]
  /** Label anchor: the highest node of the last disc. */
  polar: number
}

export const DISC_COUNT = 5
/** Camera distance in cloud radii (perspective factor = FOV / (FOV − z)). */
export const FOV = 3

const PER_COL = [6, 8, 9, 8, 6]
const DISC_RADIUS = [0.52, 0.74, 0.88, 0.74, 0.52]
const X_JITTER = 0.14

/** Mulberry32: tiny deterministic PRNG (same seed → same sequence). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Deterministic layered constellation: DISC_COUNT discs of nodes along x,
 * each node linked to its 2 nearest neighbors (y/z distance) in the next
 * disc. Edges deduplicated; incident edges indexed per node.
 */
export function buildNeuralGraph(seed: number): NeuralGraph {
  const rand = mulberry32(seed)
  const nodes: NeuralNode[] = []

  for (let c = 0; c < DISC_COUNT; c++) {
    const lx = -1 + (c / (DISC_COUNT - 1)) * 2
    for (let k = 0; k < PER_COL[c]; k++) {
      const theta = rand() * Math.PI * 2
      const rho = Math.sqrt(rand()) * DISC_RADIUS[c]
      nodes.push({
        x: lx + (rand() - 0.5) * X_JITTER,
        y: Math.cos(theta) * rho,
        z: Math.sin(theta) * rho,
        col: c,
        size: 0.6 + rand() * 0.9,
        phase: rand() * Math.PI * 2,
        edges: []
      })
    }
  }

  const edges: NeuralEdge[] = []
  const seen = new Set<number>()
  nodes.forEach((n, i) => {
    if (n.col === DISC_COUNT - 1) return
    nodes
      .map((m, j) => ({ m, j }))
      .filter(({ m }) => m.col === n.col + 1)
      .map(({ m, j }) => ({ j, d: (m.y - n.y) ** 2 + (m.z - n.z) ** 2 }))
      .sort((p, q) => p.d - q.d)
      .slice(0, 2)
      .forEach(({ j }) => {
        const a = Math.min(i, j)
        const b = Math.max(i, j)
        const key = a * nodes.length + b
        if (!seen.has(key)) {
          seen.add(key)
          edges.push({ a, b })
        }
      })
  })
  // Coverage guard (fix in esecuzione, vedi nota sotto): forward-only
  // nearest-neighbor selection can leave a node unpicked (typically in the
  // terminal disc) — attach any orphan to its nearest node in the adjacent
  // disc so every node has degree >= 1.
  const degree = new Array(nodes.length).fill(0)
  for (const e of edges) {
    degree[e.a]++
    degree[e.b]++
  }
  nodes.forEach((n, i) => {
    if (degree[i] > 0) return
    const targetCol = n.col === 0 ? 1 : n.col - 1
    let best = -1
    let bestD = Infinity
    nodes.forEach((m, j) => {
      if (m.col !== targetCol) return
      const d = (m.y - n.y) ** 2 + (m.z - n.z) ** 2
      if (d < bestD) {
        bestD = d
        best = j
      }
    })
    if (best >= 0) {
      edges.push({ a: Math.min(i, best), b: Math.max(i, best) })
      degree[i]++
      degree[best]++
    }
  })
  edges.forEach((e, k) => {
    nodes[e.a].edges.push(k)
    nodes[e.b].edges.push(k)
  })

  const byCol = Array.from({ length: DISC_COUNT }, (_, c) =>
    nodes.flatMap((n, i) => (n.col === c ? [i] : []))
  )
  const plan = byCol.map((col) =>
    col.reduce(
      (bi, i) =>
        nodes[i].y ** 2 + nodes[i].z ** 2 < nodes[bi].y ** 2 + nodes[bi].z ** 2 ? i : bi,
      col[0]
    )
  )
  const last = byCol[DISC_COUNT - 1]
  const polar = last.reduce((bi, i) => (nodes[i].y < nodes[bi].y ? i : bi), last[0])

  return { nodes, edges, byCol, plan, polar }
}

export interface ProjectedNode {
  sx: number
  sy: number
  /** Perspective factor (>1 near the lens, <1 far away). */
  scale: number
  /** Rotated depth (for back-to-front sorting). */
  z: number
}

/**
 * Rotate around the layer axis (x) by rotX — the disc spin — then swing
 * around the vertical axis (y) by rotY — the cursor parallax — and project
 * with a perspective camera on +z at distance FOV, mapped onto the viewport.
 */
export function projectNode(
  p: { x: number; y: number; z: number },
  rotX: number,
  rotY: number,
  viewport: { w: number; h: number }
): ProjectedNode {
  const cx = Math.cos(rotX)
  const sx = Math.sin(rotX)
  const cy = Math.cos(rotY)
  const sy = Math.sin(rotY)
  const y1 = p.y * cx - p.z * sx
  const z1 = p.y * sx + p.z * cx
  const x2 = p.x * cy + z1 * sy
  const z2 = -p.x * sy + z1 * cy
  const persp = FOV / (FOV - z2)
  return {
    sx: viewport.w / 2 + x2 * persp * viewport.w * 0.335,
    sy: viewport.h * 0.5 + y1 * persp * viewport.h * 0.34,
    scale: persp,
    z: z2
  }
}

/** Normalize a perspective scale to 0 (far) .. 1 (near) for alpha/size. */
export function depthNorm(scale: number): number {
  const sMin = FOV / (FOV + 1)
  const sMax = FOV / (FOV - 1)
  return Math.max(0, Math.min(1, (scale - sMin) / (sMax - sMin)))
}

export interface Hop {
  ek: number
  /** True when the traveler runs the edge b→a. */
  rev: boolean
  to: number
}

/**
 * Random hop along ANY incident edge of `from` — the free-flow propagation
 * (user decision: signals are not confined to the forward direction).
 * Returns null only for isolated nodes (degree 0, impossible by build).
 */
export function anyHop(g: NeuralGraph, from: number, rand: () => number): Hop | null {
  const list = g.nodes[from].edges
  if (list.length === 0) return null
  const ek = list[Math.floor(rand() * list.length)]
  const e = g.edges[ek]
  const rev = e.b === from
  return { ek, rev, to: rev ? e.a : e.b }
}

export interface RouteView {
  /** Active ganglion index (0..DISC_COUNT−1), −1 for an empty plan. */
  active: number
  /** Ganglia drawn as completed (0..DISC_COUNT). */
  done: number
}

/**
 * Map a plan of `total` steps onto the DISC_COUNT-ganglia route: the route
 * shows the *progression* (spec §10), the manuscript keeps the detail.
 */
export function routeView(activeIndex: number, completed: number, total: number): RouteView {
  if (total <= 0) return { active: -1, done: 0 }
  const active = Math.max(
    0,
    Math.min(
      DISC_COUNT - 1,
      Math.round((Math.max(0, activeIndex) / Math.max(1, total - 1)) * (DISC_COUNT - 1))
    )
  )
  const done = Math.max(0, Math.min(DISC_COUNT, Math.floor((completed / total) * DISC_COUNT)))
  return { active, done }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/renderer/src/composables/horizon/neuralGraph.spec.ts`
Expected: PASS (17 test).

- [ ] **Step 5: Gates + commit**

```powershell
cd frontend; npx vitest run; npm run typecheck; npm run lint
git add src/renderer/src/composables/horizon/neuralGraph.ts src/renderer/src/composables/horizon/neuralGraph.spec.ts
git commit -m "feat(horizon): neuralGraph - grafo 3D puro a dischi con proiezione e hop randomico"
```

---

### Task 2: `HorizonNeural.vue` — la rete protagonista

**Files:**
- Create: `frontend/src/renderer/src/components/horizon/HorizonNeural.vue`

Nessun component test (coerente col repo: HorizonSky/HorizonLine non ne hanno; la logica testabile vive nel modulo puro del Task 1). Il componente NON è ancora usato da nessuno: typecheck/lint devono comunque passare.

- [ ] **Step 1: Write the component**

Contenuto completo di `HorizonNeural.vue`:

```vue
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
 * Declarative (props only). One rAF loop with the full suspension pattern
 * inherited from HorizonSky: explicit redraws on resize/theme while
 * suspended, double running guard in loop(), start() never arms while
 * hidden. In quiet the loop stops once settled; a timer wakes it every
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
  let hop = null
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
    const route = routeView(props.planActiveIndex, props.planCompleted, props.planTotal)
    const p = P[graph.plan[Math.max(0, route.active)]]
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
    const pts = graph.plan.map((ni) => P[ni])
    c.save()
    c.globalAlpha = (props.dimmed ? 0.35 : 1) * intens.working
    for (let k = 0; k < DISC_COUNT - 1; k++) {
      const lit = k < route.active
      c.strokeStyle = `rgba(${lineRgb}, ${lit ? 0.6 : 0.2})`
      c.lineWidth = 1
      c.setLineDash(lit ? [] : [1, 3])
      c.beginPath()
      c.moveTo(pts[k].sx, pts[k].sy)
      c.lineTo(pts[k + 1].sx, pts[k + 1].sy)
      c.stroke()
    }
    c.setLineDash([])
    if (route.active > 0 && !reducedMotion) {
      const k = route.active - 1
      const f = (t * 0.7) % 1
      const x = pts[k].sx + (pts[k + 1].sx - pts[k].sx) * f
      const y = pts[k].sy + (pts[k + 1].sy - pts[k].sy) * f
      c.fillStyle = `rgba(${lineRgb}, 0.9)`
      c.beginPath()
      c.arc(x, y, 1.8, 0, Math.PI * 2)
      c.fill()
    }
    pts.forEach((p, k) => {
      const done = k < route.done
      const active = k === route.active
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
  }
)
</script>

<template>
  <div class="hz-neural">
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

.hz-neural-fade-enter-active,
.hz-neural-fade-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-neural-fade-enter-from,
.hz-neural-fade-leave-to {
  opacity: 0;
}
</style>
```

- [ ] **Step 2: Gates**

```powershell
cd frontend; npx vitest run; npm run typecheck; npm run lint
```
Expected: tutto verde, zero warning (il componente non è ancora referenziato: è lecito).

- [ ] **Step 3: Commit**

```powershell
git add src/renderer/src/components/horizon/HorizonNeural.vue
git commit -m "feat(horizon): HorizonNeural - rete neurale 3D full-scene con coreografie di stato"
```

---

### Task 3: Wiring — la rete sostituisce linea e cielo nella scena

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonScene.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Rewrite `HorizonScene.vue`**

Contenuto completo (sostituisce il file — sparisce `HorizonSky`, la prop `sky` e lo slot/fascia `#line`; il backdrop diventa uno slot; zoning e sfondo materico INVARIATI):

```vue
<script setup lang="ts">
/**
 * HorizonScene — the stage. Owns the vertical zoning (masthead / upper /
 * lower) and animates the content quota between scene states: that movement
 * IS the visible morph. The backdrop slot hosts the neural network
 * (HorizonNeural), full-bleed under the content zones. Pure layout: no stores.
 */
import { computed } from 'vue'
import type { HorizonState } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    state: HorizonState
    /** Long-response magazine layout (overrides the state quota). */
    magazine?: boolean
    /** Dim the whole scene (a dialog is in front). */
    dimmed?: boolean
  }>(),
  { magazine: false, dimmed: false }
)

/** Content quota per state (fraction of scene height). */
const QUOTAS: Record<HorizonState, number> = {
  quiet: 0.58,
  listening: 0.6,
  thinking: 0.6,
  responding: 0.64,
  working: 0.5
}

const quota = computed(() => (props.magazine ? 0.18 : QUOTAS[props.state]))
</script>

<template>
  <div
    class="hz-scene"
    :class="[`hz-scene--${state}`, { 'hz-scene--dimmed': dimmed }]"
    :style="{ '--quota': `${quota * 100}%` }"
  >
    <slot name="backdrop" />
    <header class="hz-scene__masthead"><slot name="masthead" /></header>
    <div class="hz-scene__upper"><slot name="upper" /></div>
    <div class="hz-scene__lower"><slot name="lower" /></div>
  </div>
</template>

<style scoped>
.hz-scene {
  position: relative;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(
      120% 85% at 50% 115%,
      rgba(var(--hz-line-rgb), var(--hz-warmth)),
      transparent 60%
    ),
    var(--surface-0);
  overflow: hidden;
  transition: opacity var(--hz-fade) ease;
}

/* Grana carta: pattern CSS puro, nessun asset esterno. */
.hz-scene::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: var(--hz-grain-opacity);
  background-image: repeating-conic-gradient(var(--hz-grain-ink) 0 25%, transparent 0 50%);
  background-size: 3px 3px;
}

/* Vignettatura: chiude la scena ai bordi. */
.hz-scene::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: radial-gradient(
    120% 100% at 50% 45%,
    transparent 60%,
    rgba(0, 0, 0, var(--hz-vignette)) 100%
  );
}

.hz-scene--dimmed {
  opacity: 0.4;
  pointer-events: none;
}

.hz-scene__masthead {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 3;
}

.hz-scene__upper {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: var(--quota);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  z-index: 2;
  transition: height var(--hz-morph) var(--ease-out-expo);
}

.hz-scene__lower {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--quota);
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 2;
  padding-top: 44px;
  padding-bottom: clamp(78px, 13vh, 112px); /* clearance for the ground bench (dock + colophon) */
  transition: top var(--hz-morph) var(--ease-out-expo);
}

@media (prefers-reduced-motion: reduce) {
  .hz-scene__upper,
  .hz-scene__lower {
    transition: none;
  }
}
</style>
```

- [ ] **Step 2: Update `HorizonView.vue` — script**

Modifiche allo script (il resto del file NON si tocca):

1. Import: rimuovere `HorizonLine`, aggiungere `HorizonNeural`:

```ts
// RIMUOVERE:
import HorizonLine from '../components/horizon/HorizonLine.vue'
// AGGIUNGERE (accanto agli altri import horizon):
import HorizonNeural from '../components/horizon/HorizonNeural.vue'
```

2. Import dal brain: rimuovere `deriveLineMode` e `deriveSkyMode` (restano `deriveSceneState`, `planView`, `HorizonSceneInputs`):

```ts
import {
  deriveSceneState,
  planView,
  type HorizonSceneInputs
} from '../composables/horizon/horizonScene'
```

3. Rimuovere i computed `lineMode` e `skyMode` (righe `const lineMode = …` e `const skyMode = …`).

4. Rinominare il computed `lineLabel` in `stateLabel` (stesso corpo, la linea non esiste più):

```ts
const stateLabel = computed(() => {
  if (voiceStore.isListening) return 'ASCOLTO'
  if (voiceStore.isProcessing) return 'ELABORO'
  if (sceneState.value === 'working')
    return planSteps.value.length > 0
      ? `LAVORO ${plan.value.activeIndex + 1} DI ${plan.value.total}`
      : 'LAVORO'
  if (sceneState.value === 'thinking') return 'RAGIONO'
  if (sceneState.value === 'responding') return 'RISPONDO'
  return ''
})
```

- [ ] **Step 3: Update `HorizonView.vue` — template**

1. Il tag `HorizonScene` perde `:sky`:

```html
<HorizonScene :state="sceneState" :magazine="magazine" :dimmed="sceneDimmed">
```

2. Subito dentro, come PRIMO template, il backdrop (la rete riceve i lavori della linea):

```html
      <template #backdrop>
        <HorizonNeural
          :state="sceneState"
          :audio-level="voiceStore.audioLevel"
          :speaking="voiceStore.isSpeaking"
          :plan-total="sceneState === 'working' ? planSteps.length : 0"
          :plan-active-index="plan.activeIndex"
          :plan-completed="plan.completed"
          :plan-step-label="plan.statusSentence"
          :label="stateLabel"
          :dimmed="!isConnected"
        />
      </template>
```

3. Rimuovere TUTTO il blocco `<template #line>…</template>` (il `<HorizonLine …/>` con le sue bind).

4. Rimuovere dal template `#upper` il paragrafo dello stato (deciso in design review — il suo contenuto vive nell'annotazione della rotta e nel manoscritto):

```html
<!-- RIMUOVERE: -->
<p v-if="sceneState === 'working' && plan.statusSentence" class="horizon-view__status">
  <em>{{ plan.statusSentence }}</em>
</p>
```

5. Nello `<style scoped>` rimuovere l'intero blocco `.horizon-view__status { … }`.

- [ ] **Step 4: Gates**

```powershell
cd frontend; npx vitest run; npm run typecheck; npm run lint
```
Expected: verde. `HorizonLine.vue`/`HorizonSky.vue` sono ancora nel repo ma non più referenziati (si eliminano nel Task 4 — typecheck resta verde perché i file sono ancora validi).

- [ ] **Step 5: Commit**

```powershell
git add src/renderer/src/components/horizon/HorizonScene.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): la rete neurale sostituisce linea e cielo nella scena"
```

---

### Task 4: Rimozione — HorizonLine/HorizonSky e i modi linea/sky del brain

**Files:**
- Delete: `frontend/src/renderer/src/components/horizon/HorizonLine.vue`
- Delete: `frontend/src/renderer/src/components/horizon/HorizonSky.vue`
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.ts`
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.spec.ts`

- [ ] **Step 1: Update `horizonScene.spec.ts` (test-first: rispecchia il brain che vogliamo)**

1. Nell'import da `'./horizonScene'` rimuovere `deriveLineMode`, `deriveSkyMode`, `notchPositions` (restano gli altri).
2. Rimuovere per intero i blocchi:
   - `describe('deriveLineMode', …)` (righe ~106-115)
   - `describe('deriveLineMode — thinking', …)` (righe ~117-123)
   - `describe('deriveSkyMode', …)` (righe ~125-140)
   - `describe('notchPositions', …)` (righe ~257-263)

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts`
Expected: PASS dei test rimasti ma… il file compila ancora perché le export esistono. Procedere: il fallimento atteso arriva DOPO lo Step 3 se qualche riferimento è rimasto — l'ordine qui serve solo a non lasciare mai i test rotti.

- [ ] **Step 3: Update `horizonScene.ts`**

Rimuovere (il resto del file resta identico):

1. Il tipo `HorizonSkyMode` e il suo commento (righe ~18-19).
2. Il tipo `HorizonLineMode` e il suo commento (righe ~21-22).
3. La funzione `deriveLineMode` intera con la docstring (righe ~51-65).
4. La funzione `notchPositions` intera con la docstring (righe ~67-76).
5. La funzione `deriveSkyMode` intera con la docstring (righe ~97-102).
6. Aggiornare la docstring di testa del file: la frase «Maps plain snapshots of the voice/chat/tasks stores to a single scene state and the line's visual mechanic» diventa:

```ts
 * Maps plain snapshots of the voice/chat/tasks stores to a single scene
 * state. The neural backdrop (HorizonNeural) derives its choreography from
 * that state directly; the plan/manuscript/thinking helpers live here.
```

- [ ] **Step 4: Delete the two components**

```powershell
git rm src/renderer/src/components/horizon/HorizonLine.vue src/renderer/src/components/horizon/HorizonSky.vue
```

- [ ] **Step 5: Gates**

```powershell
cd frontend; npx vitest run; npm run typecheck; npm run lint
```
Expected: verde (nessun riferimento residuo: il Task 3 ha già staccato scena e view).

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "refactor(horizon): rimozione HorizonLine/HorizonSky e modi linea/sky dal brain"
```

---

### Task 5: Sweep finale — riferimenti residui e gates completi

**Files:**
- Nessun file previsto (solo verifiche; eventuali residui trovati si correggono qui)

- [ ] **Step 1: Grep dei residui**

Run (da `frontend/`):

```powershell
npx eslint . --max-warnings 0 | Out-Null; git grep -nE "HorizonLine|HorizonSky|deriveLineMode|deriveSkyMode|notchPositions|HorizonLineMode|HorizonSkyMode|lineQuota|horizon-view__status|hz-line__" -- src
```

Expected: NESSUN match in `src/` (l'unico nome legittimo che resta è il token CSS `--hz-line-rgb`, che è l'inchiostro condiviso — il grep sopra non lo intercetta perché cerca `hz-line__`).
Se emergono match: correggerli qui (rimozione/rinomina) e includerli nel commit di questo task.

- [ ] **Step 2: Full gates**

```powershell
cd frontend; npx vitest run; npm run typecheck; npm run lint
```
Expected: vitest verde (≈350 − 10 test linea/sky + 17 neuralGraph ≈ 357), typecheck node+web verde, lint ZERO warning.

- [ ] **Step 3: Commit (solo se lo Step 1 ha prodotto correzioni)**

```powershell
git add -A
git commit -m "chore(horizon): sweep finale pivot rete neurale"
```

---

## Post-implementazione (fuori dai task, con l'utente)

- **Verifica manuale nell'app viva** (spec §11): 5 coreografie (quiete+sogno, membrana, sweep randomici, rotta+posa, cadenza+anelli), parallasse (solo pointer fine), sospensione in quiete (CPU ferma tra i sogni), entrambi i temi, `prefers-reduced-motion`, `dimmed`/disconnesso, viewport basso, piano >5 passi (rotta proporzionale). Assorbe la parte superstite della checklist Vivo §13 (manoscritto, banco, finestre).
- Aggiornare l'handoff/memoria di sessione con l'esito.

## Fix in esecuzione (annotati, prevale il codice committato)

- **T1 — coverage guard in `buildNeuralGraph`**: l'algoritmo originale creava archi solo «in avanti»
  (disco c → c+1), quindi un nodo dell'ultimo disco poteva restare orfano (grado 0) — al seed 197
  succedeva al nodo 35, rompendo il test `degree >= 1` e `anyHop`. Trovato dall'implementer T1 in
  TDD; fix: post-pass deterministico che aggancia ogni orfano al nodo più vicino del disco
  adiacente (già integrato nel blocco di codice del Task 1 qui sopra). Commit `7c1f175`.
- **T1 — fix di quality review** (commit `8e55b00`): test sweep multi-seed (50 seed) degli
  invarianti strutturali (adiacenza/dedup/grado ≥ 1 — la classe di bug del coverage guard);
  `X_JITTER` esportato e usato dal test del layout al posto del magic 0.07; assert dei criteri di
  selezione `plan` (min y²+z² per disco) e `polar` (min y ultimo disco); docstring: divergenza
  prospettica per ‖p‖ → FOV in `projectNode`, contratto `rand ∈ [0,1)` in `anyHop`; commento del
  guard esplicita che solo l'ultimo disco può orfanare (ramo col-0 difensivo).

## Self-review del piano

- **Copertura spec**: §3.1→Task 1; §3.2→Task 2; §3.3→Task 4; §3.4→Task 3; §4/§5/§6 (coreografie, parallasse, sospensione+sogno, reduced-motion)→Task 2; §7 token→Task 2 (readTheme, var()); §9 file→Task 1-4; §10 edge case→`routeView` (Task 1) + guardie in Task 2 (working senza piano: `planTotal===0` → solo brusio; dimmed→globalAlpha; NaN audio→clamp); §11 test/gates→Task 1, 4, 5.
- **Tipi coerenti**: `ProjectedNode`/`NeuralGraph`/`Hop`/`RouteView` definiti nel Task 1 e importati identici nel Task 2; `HorizonState` invariato dal brain; props del Task 2 = bind del Task 3.
- **Niente placeholder**: ogni step con codice o comando concreto.
