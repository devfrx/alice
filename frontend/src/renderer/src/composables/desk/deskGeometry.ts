/**
 * deskGeometry.ts — Pure geometry for the Horizon desk's floating windows.
 *
 * No Vue imports: clamping, cascade placement, z compaction and arrange
 * presets are plain functions so the whole window mechanic is unit testable
 * (same philosophy as workspace/tilingTree.ts).
 */

export interface DeskRect {
  x: number
  y: number
  w: number
  h: number
}

export interface DeskViewport {
  w: number
  h: number
}

/** One floating window (presentation state only — domain state lives elsewhere). */
export interface DeskWindowState {
  id: string
  moduleId: string
  params?: Record<string, unknown>
  rect: DeskRect
  z: number
  minimized: boolean
}

export type DeskArrangePreset = 'cascade' | 'tile'

/** Default size for a freshly opened window. */
export const DEFAULT_SIZE = { w: 520, h: 380 } as const
/** Smallest size a window can be resized/clamped to. */
export const MIN_SIZE = { w: 280, h: 180 } as const
/** Horizontal sliver of a window that must always stay on-screen. */
export const EDGE_VISIBLE = 48
/** Vertical strip (the header) that must always stay reachable. */
export const HEADER_VISIBLE = 32

const CASCADE_STEP = 44
const CASCADE_WRAP = 8
const TILE_MARGIN = 16
const TILE_GAP = 12

function clampNum(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

/** Clamp a rect so it fits the viewport and its header stays reachable. */
export function clampRect(rect: DeskRect, vp: DeskViewport): DeskRect {
  const w = clampNum(rect.w, MIN_SIZE.w, Math.max(MIN_SIZE.w, vp.w))
  const h = clampNum(rect.h, MIN_SIZE.h, Math.max(MIN_SIZE.h, vp.h))
  const x = clampNum(rect.x, EDGE_VISIBLE - w, Math.max(EDGE_VISIBLE - w, vp.w - EDGE_VISIBLE))
  const y = clampNum(rect.y, 0, Math.max(0, vp.h - HEADER_VISIBLE))
  return { x, y, w, h }
}

/** Default placement for the i-th opened window: a wrapping cascade. */
export function cascadeRect(index: number, vp: DeskViewport): DeskRect {
  const i = index % CASCADE_WRAP
  const x0 = Math.round(vp.w * 0.18)
  const y0 = Math.round(vp.h * 0.12)
  return clampRect(
    { x: x0 + i * CASCADE_STEP, y: y0 + i * CASCADE_STEP, w: DEFAULT_SIZE.w, h: DEFAULT_SIZE.h },
    vp
  )
}

/** Re-clamp every window (viewport changed, layout restored). */
export function normalizeWindows(windows: DeskWindowState[], vp: DeskViewport): DeskWindowState[] {
  return windows.map((w) => ({ ...w, rect: clampRect(w.rect, vp) }))
}

/** Compact z values to 0..n-1 preserving the stacking order. */
export function compactZ(windows: DeskWindowState[]): DeskWindowState[] {
  return windows
    .slice()
    .sort((a, b) => a.z - b.z)
    .map((w, i) => ({ ...w, z: i }))
}

/** Rects for the arrange presets, one per (non-minimized) window. */
export function arrangeRects(
  count: number,
  vp: DeskViewport,
  preset: DeskArrangePreset
): DeskRect[] {
  if (count <= 0) return []
  if (preset === 'cascade') {
    return Array.from({ length: count }, (_, i) => cascadeRect(i, vp))
  }
  const cols = Math.ceil(Math.sqrt(count))
  const rows = Math.ceil(count / cols)
  const cellW = (vp.w - 2 * TILE_MARGIN - (cols - 1) * TILE_GAP) / cols
  const cellH = (vp.h - 2 * TILE_MARGIN - (rows - 1) * TILE_GAP) / rows
  return Array.from({ length: count }, (_, i) => {
    const c = i % cols
    const r = Math.floor(i / cols)
    return clampRect(
      {
        x: Math.round(TILE_MARGIN + c * (cellW + TILE_GAP)),
        y: Math.round(TILE_MARGIN + r * (cellH + TILE_GAP)),
        w: Math.round(cellW),
        h: Math.round(cellH)
      },
      vp
    )
  })
}
