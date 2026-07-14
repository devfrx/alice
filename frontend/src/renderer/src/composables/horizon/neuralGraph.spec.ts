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
