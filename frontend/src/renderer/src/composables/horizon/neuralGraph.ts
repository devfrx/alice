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
  // Coverage guard: forward-only nearest-neighbor selection can leave a
  // node unpicked (typically in the terminal disc) — attach any orphan to
  // its nearest node in the adjacent disc so every node has degree >= 1.
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
      (bi, i) => (nodes[i].y ** 2 + nodes[i].z ** 2 < nodes[bi].y ** 2 + nodes[bi].z ** 2 ? i : bi),
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
