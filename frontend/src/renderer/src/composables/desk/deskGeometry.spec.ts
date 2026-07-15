import { describe, it, expect } from 'vitest'
import {
  MIN_SIZE,
  EDGE_VISIBLE,
  HEADER_VISIBLE,
  clampRect,
  cascadeRect,
  compactZ,
  arrangeRects
} from './deskGeometry'
import type { DeskWindowState } from './deskGeometry'

const VP = { w: 1200, h: 800 }

function win(partial: Partial<DeskWindowState>): DeskWindowState {
  return {
    id: partial.id ?? 'w1',
    moduleId: partial.moduleId ?? 'chart',
    rect: partial.rect ?? { x: 0, y: 0, w: 400, h: 300 },
    z: partial.z ?? 0,
    minimized: partial.minimized ?? false,
    params: partial.params
  }
}

describe('clampRect', () => {
  it('enforces minimum size', () => {
    const r = clampRect({ x: 10, y: 10, w: 50, h: 40 }, VP)
    expect(r.w).toBe(MIN_SIZE.w)
    expect(r.h).toBe(MIN_SIZE.h)
  })

  it('caps size to the viewport', () => {
    const r = clampRect({ x: 0, y: 0, w: 5000, h: 5000 }, VP)
    expect(r.w).toBe(VP.w)
    expect(r.h).toBe(VP.h)
  })

  it('keeps the header strip reachable vertically', () => {
    const above = clampRect({ x: 100, y: -500, w: 400, h: 300 }, VP)
    expect(above.y).toBe(0)
    const below = clampRect({ x: 100, y: 5000, w: 400, h: 300 }, VP)
    expect(below.y).toBe(VP.h - HEADER_VISIBLE)
  })

  it('keeps a horizontal sliver visible on both sides', () => {
    const left = clampRect({ x: -5000, y: 10, w: 400, h: 300 }, VP)
    expect(left.x).toBe(EDGE_VISIBLE - 400)
    const right = clampRect({ x: 5000, y: 10, w: 400, h: 300 }, VP)
    expect(right.x).toBe(VP.w - EDGE_VISIBLE)
  })
})

describe('cascadeRect', () => {
  it('offsets each successive window and stays clamped', () => {
    const a = cascadeRect(0, VP)
    const b = cascadeRect(1, VP)
    expect(b.x).toBeGreaterThan(a.x)
    expect(b.y).toBeGreaterThan(a.y)
    const far = cascadeRect(200, VP)
    expect(far.x + far.w).toBeGreaterThan(EDGE_VISIBLE)
    expect(far.y).toBeLessThanOrEqual(VP.h - HEADER_VISIBLE)
  })

  it('wraps back to the origin after 8 windows', () => {
    expect(cascadeRect(8, VP)).toEqual(cascadeRect(0, VP))
  })
})

describe('compactZ', () => {
  it('reassigns z to 0..n-1 preserving stacking order', () => {
    const out = compactZ([win({ id: 'a', z: 40 }), win({ id: 'b', z: 7 }), win({ id: 'c', z: 99 })])
    const byId = Object.fromEntries(out.map((w) => [w.id, w.z]))
    expect(byId).toEqual({ b: 0, a: 1, c: 2 })
  })
})

describe('arrangeRects', () => {
  it('tile produces one clamped rect per window in a grid', () => {
    const rects = arrangeRects(5, VP, 'tile')
    expect(rects).toHaveLength(5)
    for (const r of rects) {
      expect(r.w).toBeGreaterThanOrEqual(MIN_SIZE.w)
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.x + r.w).toBeLessThanOrEqual(VP.w)
    }
  })

  it('cascade mirrors cascadeRect', () => {
    expect(arrangeRects(3, VP, 'cascade')).toEqual([
      cascadeRect(0, VP),
      cascadeRect(1, VP),
      cascadeRect(2, VP)
    ])
  })
})
