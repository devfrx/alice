# Horizon "Atelier" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ricostruire la vista assistente (`/assistant`) come scrivania ambientale con finestre flottanti OS-like sui moduli del catalogo Workspace, pilotabili da UI e agente tramite gli stessi comandi.

**Architecture:** Nuovo store Pinia `desk` (geometrie/z/focus, surface-agnostic) + componenti `DeskWindow`/`DeskSurface`/`DeskDock` con chrome atelier sui token esistenti; contenuti = `MODULE_REGISTRY` esistente + nuovo modulo Attività; comandi `window.*` registrati nel Command Registry frontend (nessuna modifica backend). La scena ambientale salva la logica pura esistente (scene brain, pacer, artifacts) ed estrae il wiring di `HorizonView.vue` in composable.

**Tech Stack:** Vue 3 `<script setup lang="ts">`, Pinia setup-store, Vitest, token CSS di `theme.css`/`horizon.css`, kit `components/ui`.

**Spec:** `docs/superpowers/specs/2026-07-13-horizon-atelier-redesign-design.md` (leggerla prima: contiene le decisioni e i 27 edge case).

**Convenzioni vincolanti** (da CLAUDE.md e regole kit):
- Solo token, mai valori hardcoded; entrambi i temi devono funzionare.
- Kit first; override solo compound (`.mia-classe.ui-btn`, `:deep(.ui-*__el)`).
- Mai `outline: none` senza ripristino `:focus-visible`.
- `npm run typecheck` è il gate obbligatorio del FE.
- Tutti i comandi si lanciano da `frontend/` in PowerShell.

---

### Task 0: Branch di lavoro

- [ ] **Step 0.1:** Creare il branch (o worktree via superpowers:using-git-worktrees):

```powershell
git checkout -b rework/horizon-atelier
```

---

### Task 1: `deskGeometry` — matematica pura delle finestre

**Files:**
- Create: `frontend/src/renderer/src/composables/desk/deskGeometry.ts`
- Test: `frontend/src/renderer/src/composables/desk/deskGeometry.spec.ts`

- [ ] **Step 1.1: Scrivere il test che fallisce**

```ts
// deskGeometry.spec.ts
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
```

- [ ] **Step 1.2: Verificare che fallisca**

Run: `npx vitest run src/renderer/src/composables/desk/deskGeometry.spec.ts`
Expected: FAIL (modulo inesistente).

- [ ] **Step 1.3: Implementazione**

```ts
// deskGeometry.ts
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
export function normalizeWindows(
  windows: DeskWindowState[],
  vp: DeskViewport
): DeskWindowState[] {
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
```

- [ ] **Step 1.4: Verificare che passi**

Run: `npx vitest run src/renderer/src/composables/desk/deskGeometry.spec.ts`
Expected: PASS (9 test).

- [ ] **Step 1.5: Commit**

```powershell
git add src/renderer/src/composables/desk/
git commit -m "feat(desk): pure window geometry (clamp, cascade, z, arrange)"
```

---

### Task 2: Store `desk`

**Files:**
- Create: `frontend/src/renderer/src/stores/desk.ts`
- Test: `frontend/src/renderer/src/stores/desk.spec.ts`

- [ ] **Step 2.1: Scrivere il test che fallisce**

```ts
// desk.spec.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDeskStore, migrateDeskLayout, DESK_LAYOUT_KEY } from './desk'

// vitest node env: minimal localStorage stub (same failure modes as the browser).
const mem = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => {
    mem.set(k, String(v))
  },
  removeItem: (k: string) => {
    mem.delete(k)
  }
})

beforeEach(() => {
  mem.clear()
  setActivePinia(createPinia())
})

describe('migrateDeskLayout', () => {
  it('resets on garbage / wrong version', () => {
    expect(migrateDeskLayout(null).windows).toEqual([])
    expect(migrateDeskLayout({ version: 2, windows: [] }).windows).toEqual([])
  })

  it('drops windows of unregistered modules, keeps valid ones', () => {
    const raw = {
      version: 1,
      windows: [
        { id: 'a', moduleId: 'chart', rect: { x: 1, y: 2, w: 400, h: 300 }, z: 3, minimized: false },
        { id: 'b', moduleId: 'ghost', rect: { x: 1, y: 2, w: 400, h: 300 }, z: 1, minimized: false }
      ]
    }
    const out = migrateDeskLayout(raw, (id) => id === 'chart')
    expect(out.windows.map((w) => w.id)).toEqual(['a'])
  })

  it('drops malformed windows (rect not numeric)', () => {
    const raw = {
      version: 1,
      windows: [{ id: 'a', moduleId: 'chart', rect: { x: 'no' }, z: 0, minimized: false }]
    }
    expect(migrateDeskLayout(raw, () => true).windows).toEqual([])
  })
})

describe('desk store', () => {
  it('opens, focuses and closes windows with monotonic z', () => {
    const desk = useDeskStore()
    const a = desk.openWindow('chart')
    const b = desk.openWindow('whiteboard')
    expect(a).not.toBeNull()
    expect(b).not.toBeNull()
    expect(desk.windows).toHaveLength(2)
    expect(desk.focusedId).toBe(b)
    desk.focusWindow(a as string)
    expect(desk.focusedId).toBe(a)
    expect(desk.closeWindow(b as string)).toBe(true)
    expect(desk.windows).toHaveLength(1)
  })

  it('returns null for unknown modules', () => {
    const desk = useDeskStore()
    expect(desk.openWindow('does-not-exist')).toBeNull()
  })

  it('singleton modules focus the existing window instead of duplicating', () => {
    const desk = useDeskStore()
    const first = desk.openWindow('chat')
    desk.minimizeWindow(first as string)
    const second = desk.openWindow('chat')
    expect(second).toBe(first)
    expect(desk.windows).toHaveLength(1)
    expect(desk.windows[0].minimized).toBe(false)
  })

  it('ignores external moves while the user is dragging that window', () => {
    const desk = useDeskStore()
    const id = desk.openWindow('chart') as string
    desk.setDragging(id)
    const before = desk.windows[0].rect
    expect(desk.moveWindow(id, before.x + 100, before.y + 100, 'external')).toBe(false)
    expect(desk.windows[0].rect).toEqual(before)
    desk.setDragging(null)
    expect(desk.moveWindow(id, before.x + 100, before.y + 100, 'external')).toBe(true)
  })

  it('persists with compacted z and survives corrupted storage', () => {
    const desk = useDeskStore()
    desk.openWindow('chart')
    desk.openWindow('whiteboard')
    const saved = JSON.parse(mem.get(DESK_LAYOUT_KEY) as string)
    expect(saved.version).toBe(1)
    expect(saved.windows.map((w: { z: number }) => w.z).sort()).toEqual([0, 1])
    mem.set(DESK_LAYOUT_KEY, '{not json')
    setActivePinia(createPinia())
    expect(useDeskStore().windows).toEqual([])
  })

  it('clamps geometry when the viewport shrinks', () => {
    const desk = useDeskStore()
    const id = desk.openWindow('chart') as string
    desk.moveWindow(id, 1000, 700)
    desk.setViewport(600, 400)
    const r = desk.windows[0].rect
    expect(r.x).toBeLessThanOrEqual(600 - 48)
    expect(r.y).toBeLessThanOrEqual(400 - 32)
  })

  it('blurWindows releases focus without closing', () => {
    const desk = useDeskStore()
    desk.openWindow('chart')
    expect(desk.focusedId).not.toBeNull()
    desk.blurWindows()
    expect(desk.focusedId).toBeNull()
    expect(desk.windows).toHaveLength(1)
  })

  it('listWindows returns a serializable snapshot', () => {
    const desk = useDeskStore()
    const id = desk.openWindow('chart') as string
    const snap = desk.listWindows()
    expect(snap).toEqual([
      {
        id,
        module: 'chart',
        title: 'Grafico',
        rect: desk.windows[0].rect,
        minimized: false,
        focused: true
      }
    ])
  })
})
```

- [ ] **Step 2.2: Verificare che fallisca**

Run: `npx vitest run src/renderer/src/stores/desk.spec.ts`
Expected: FAIL.

- [ ] **Step 2.3: Implementazione**

```ts
// stores/desk.ts
/**
 * Pinia store for the Horizon desk: free-floating module windows (geometry,
 * stacking order, focus) with versioned localStorage persistence.
 *
 * Presentation state ONLY — closing a window never destroys domain state
 * (terminal sessions, plan, conversation…), which lives in dedicated stores.
 *
 * Surface-agnostic by design (spec §2): no import from views/ or horizon
 * components, so promoting the desk app-wide later is a mount-point change.
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import {
  arrangeRects,
  cascadeRect,
  clampRect,
  compactZ,
  normalizeWindows
} from '../composables/desk/deskGeometry'
import type {
  DeskArrangePreset,
  DeskRect,
  DeskViewport,
  DeskWindowState
} from '../composables/desk/deskGeometry'
import { getModule, isModuleRegistered } from '../composables/workspace/moduleRegistry'

export const DESK_LAYOUT_KEY = 'alice_desk_layout_v1'

export interface DeskLayout {
  version: 1
  windows: DeskWindowState[]
}

/** Snapshot shape returned by `listWindows` (feeds the `window.list` command). */
export interface DeskWindowSnapshot {
  id: string
  module: string
  title: string
  rect: DeskRect
  minimized: boolean
  focused: boolean
}

function _isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function _isFiniteNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function _validateWindow(raw: unknown, isRegistered: (id: string) => boolean): raw is DeskWindowState {
  if (!_isObject(raw)) return false
  if (typeof raw.id !== 'string' || raw.id === '') return false
  if (typeof raw.moduleId !== 'string' || !isRegistered(raw.moduleId)) return false
  if (!_isObject(raw.rect)) return false
  const r = raw.rect
  if (!_isFiniteNum(r.x) || !_isFiniteNum(r.y) || !_isFiniteNum(r.w) || !_isFiniteNum(r.h))
    return false
  if (!_isFiniteNum(raw.z)) return false
  if (typeof raw.minimized !== 'boolean') return false
  if (raw.params !== undefined && !_isObject(raw.params)) return false
  return true
}

/**
 * Validate/migrate a persisted value. Unlike the workspace tree (where a bad
 * node poisons the structure), windows are independent: invalid or
 * unregistered ones are dropped individually, valid ones survive.
 */
export function migrateDeskLayout(
  raw: unknown,
  isRegistered: (id: string) => boolean = () => true
): DeskLayout {
  if (!_isObject(raw) || raw.version !== 1 || !Array.isArray(raw.windows)) {
    return { version: 1, windows: [] }
  }
  const windows = compactZ(raw.windows.filter((w): w is DeskWindowState => _validateWindow(w, isRegistered)))
  return { version: 1, windows }
}

function loadDesk(): DeskLayout {
  try {
    const raw = localStorage.getItem(DESK_LAYOUT_KEY)
    if (raw === null) return { version: 1, windows: [] }
    return migrateDeskLayout(JSON.parse(raw) as unknown, isModuleRegistered)
  } catch {
    return { version: 1, windows: [] }
  }
}

export const useDeskStore = defineStore('desk', () => {
  const windows = ref<DeskWindowState[]>(loadDesk().windows)
  /** Measured by DeskSurface; a sane default until the first observation. */
  const viewport = ref<DeskViewport>({ w: 1280, h: 800 })
  /** Explicit focus (transient, not persisted). Esc releases it to the scene. */
  const focusedId = ref<string | null>(null)
  /** Window currently under a user pointer-drag: external moves are ignored. */
  const draggingId = ref<string | null>(null)

  const ordered = computed<DeskWindowState[]>(() => windows.value.slice().sort((a, b) => a.z - b.z))

  /** moduleId → count of open (non-minimized) and minimized windows. */
  const openByModule = computed<Record<string, { open: number; minimized: number }>>(() => {
    const out: Record<string, { open: number; minimized: number }> = {}
    for (const w of windows.value) {
      const slot = (out[w.moduleId] ??= { open: 0, minimized: 0 })
      if (w.minimized) slot.minimized += 1
      else slot.open += 1
    }
    return out
  })

  function _persist(): void {
    try {
      windows.value = compactZ(windows.value)
      localStorage.setItem(
        DESK_LAYOUT_KEY,
        JSON.stringify({ version: 1, windows: windows.value } satisfies DeskLayout)
      )
    } catch {
      /* localStorage may be unavailable */
    }
  }

  function _byId(id: string): DeskWindowState | undefined {
    return windows.value.find((w) => w.id === id)
  }

  function _nextZ(): number {
    return windows.value.reduce((m, w) => Math.max(m, w.z), -1) + 1
  }

  /**
   * Open a window for `moduleId`. Singleton modules focus (and restore) the
   * existing window instead of duplicating. Returns the window id, or null
   * when the module is not registered.
   */
  function openWindow(moduleId: string, params?: Record<string, unknown>): string | null {
    const def = getModule(moduleId)
    if (def === undefined) return null
    if (def.singleton === true) {
      const existing = windows.value.find((w) => w.moduleId === moduleId)
      if (existing !== undefined) {
        focusWindow(existing.id)
        return existing.id
      }
    }
    const win: DeskWindowState = {
      id: crypto.randomUUID(),
      moduleId,
      params,
      rect: cascadeRect(windows.value.length, viewport.value),
      z: _nextZ(),
      minimized: false
    }
    windows.value = [...windows.value, win]
    focusedId.value = win.id
    _persist()
    return win.id
  }

  function closeWindow(id: string): boolean {
    if (_byId(id) === undefined) return false
    windows.value = windows.value.filter((w) => w.id !== id)
    if (focusedId.value === id) focusedId.value = null
    _persist()
    return true
  }

  /** Raise + restore + focus. */
  function focusWindow(id: string): boolean {
    const win = _byId(id)
    if (win === undefined) return false
    win.z = _nextZ()
    win.minimized = false
    focusedId.value = id
    _persist()
    return true
  }

  /** Release keyboard/visual focus back to the ambient scene (Esc). */
  function blurWindows(): void {
    focusedId.value = null
  }

  function moveWindow(id: string, x: number, y: number, source: 'user' | 'external' = 'user'): boolean {
    const win = _byId(id)
    if (win === undefined) return false
    if (source === 'external' && draggingId.value === id) return false
    win.rect = clampRect({ ...win.rect, x, y }, viewport.value)
    _persist()
    return true
  }

  function resizeWindow(id: string, rect: DeskRect, source: 'user' | 'external' = 'user'): boolean {
    const win = _byId(id)
    if (win === undefined) return false
    if (source === 'external' && draggingId.value === id) return false
    win.rect = clampRect(rect, viewport.value)
    _persist()
    return true
  }

  function minimizeWindow(id: string): boolean {
    const win = _byId(id)
    if (win === undefined) return false
    win.minimized = true
    if (focusedId.value === id) focusedId.value = null
    _persist()
    return true
  }

  function restoreWindow(id: string): boolean {
    return focusWindow(id)
  }

  /** Apply an arrange preset to the non-minimized windows (stacking order). */
  function arrangeWindows(preset: DeskArrangePreset): void {
    const visible = ordered.value.filter((w) => !w.minimized)
    const rects = arrangeRects(visible.length, viewport.value, preset)
    visible.forEach((w, i) => {
      const target = _byId(w.id)
      if (target !== undefined) target.rect = rects[i]
    })
    _persist()
  }

  /** Called by DeskSurface's ResizeObserver; re-clamps every window. */
  function setViewport(w: number, h: number): void {
    viewport.value = { w, h }
    windows.value = normalizeWindows(windows.value, viewport.value)
    _persist()
  }

  function setDragging(id: string | null): void {
    draggingId.value = id
  }

  /** Serializable snapshot for the `window.list` command. */
  function listWindows(): DeskWindowSnapshot[] {
    return ordered.value.map((w) => ({
      id: w.id,
      module: w.moduleId,
      title: getModule(w.moduleId)?.label ?? w.moduleId,
      rect: { ...w.rect },
      minimized: w.minimized,
      focused: focusedId.value === w.id
    }))
  }

  function resetDesk(): void {
    windows.value = []
    focusedId.value = null
    _persist()
  }

  // Safety net for direct mutations (mirrors the workspace store).
  watch(windows, _persist, { deep: true })

  return {
    windows,
    viewport,
    focusedId,
    draggingId,
    ordered,
    openByModule,
    openWindow,
    closeWindow,
    focusWindow,
    blurWindows,
    moveWindow,
    resizeWindow,
    minimizeWindow,
    restoreWindow,
    arrangeWindows,
    setViewport,
    setDragging,
    listWindows,
    resetDesk
  }
})
```

- [ ] **Step 2.4: Verificare che passi**

Run: `npx vitest run src/renderer/src/stores/desk.spec.ts`
Expected: PASS.

- [ ] **Step 2.5: Commit**

```powershell
git add src/renderer/src/stores/desk.ts src/renderer/src/stores/desk.spec.ts
git commit -m "feat(desk): pinia store for floating windows (z-order, focus, persistence)"
```

---

### Task 3: Comandi agente `window.*`

**Files:**
- Create: `frontend/src/renderer/src/commands/desk.ts`
- Test: `frontend/src/renderer/src/commands/desk.spec.ts`
- Modify: `frontend/src/renderer/src/commands/index.ts` (barrel)
- Modify: `frontend/src/renderer/src/App.vue:33` (install)

- [ ] **Step 3.1: Scrivere il test che fallisce**

```ts
// commands/desk.spec.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { installDeskCommands, DESK_COMMAND_NAMES } from './desk'
import { useDeskStore } from '../stores/desk'

vi.stubGlobal('localStorage', {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
})

function fakeRouter(currentName: string): Router {
  return {
    push: vi.fn().mockResolvedValue(undefined),
    currentRoute: { value: { name: currentName } }
  } as unknown as Router
}

beforeEach(() => {
  setActivePinia(createPinia())
  commandRegistry.clear()
})

describe('installDeskCommands', () => {
  it('registers every window.* command with the expected capability', () => {
    installDeskCommands(fakeRouter('assistant'))
    const byName = new Map(commandRegistry.list().map((c) => [c.name, c]))
    expect([...byName.keys()].sort()).toEqual([...DESK_COMMAND_NAMES].sort())
    expect(byName.get('window.open')?.capability).toBe('navigation')
    expect(byName.get('window.focus')?.capability).toBe('navigation')
    expect(byName.get('window.arrange')?.capability).toBe('navigation')
    expect(byName.get('window.list')?.capability).toBe('read')
    expect(byName.get('window.close')?.capability).toBe('mutate')
    for (const c of byName.values()) expect(c.exposeToAgent).toBe(true)
  })

  it('is idempotent (HMR re-install)', () => {
    const r = fakeRouter('assistant')
    installDeskCommands(r)
    expect(() => installDeskCommands(r)).not.toThrow()
  })

  it('window.open creates a window and navigates to assistant when elsewhere', async () => {
    const router = fakeRouter('workspace')
    installDeskCommands(router)
    const result = (await commandRegistry.execute('window.open', { module: 'chart' })) as {
      window_id: string
    }
    expect(router.push).toHaveBeenCalledWith({ name: 'assistant' })
    expect(useDeskStore().windows[0].id).toBe(result.window_id)
  })

  it('window.open does not navigate when already on assistant', async () => {
    const router = fakeRouter('assistant')
    installDeskCommands(router)
    await commandRegistry.execute('window.open', { module: 'chart' })
    expect(router.push).not.toHaveBeenCalled()
  })

  it('window.open rejects unknown modules with a clean error', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await expect(commandRegistry.execute('window.open', { module: 'nope' })).rejects.toThrow(
      /modulo|module/i
    )
  })

  it('window.close / window.focus reject unknown ids', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await expect(commandRegistry.execute('window.close', { window_id: 'ghost' })).rejects.toThrow()
    await expect(commandRegistry.execute('window.focus', { window_id: 'ghost' })).rejects.toThrow()
  })

  it('window.list returns the snapshot', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await commandRegistry.execute('window.open', { module: 'chart' })
    const out = (await commandRegistry.execute('window.list', {})) as { windows: unknown[] }
    expect(out.windows).toHaveLength(1)
  })
})
```

- [ ] **Step 3.2: Verificare che fallisca**

Run: `npx vitest run src/renderer/src/commands/desk.spec.ts`
Expected: FAIL.

- [ ] **Step 3.3: Implementazione**

```ts
// commands/desk.ts
/**
 * Desk window commands (spec §5): the agent drives Horizon's floating
 * windows through the SAME implementations the UI uses (desk store actions).
 *
 * Capabilities follow the §7 permission matrix: open/focus/arrange are
 * `navigation`, list is `read`, close is `mutate` (denied in plan tier,
 * confirmed in strict). `window` is not a guardrail domain.
 */
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { MODULE_REGISTRY } from '../composables/workspace/moduleRegistry'
import { useDeskStore } from '../stores/desk'

export interface WindowOpenArgs {
  module: string
  params?: Record<string, unknown>
}
export interface WindowIdArgs {
  window_id: string
}
export interface WindowArrangeArgs {
  preset: 'cascade' | 'tile'
}

export const DESK_COMMAND_NAMES = [
  'window.open',
  'window.focus',
  'window.list',
  'window.close',
  'window.arrange'
] as const

export function installDeskCommands(router: Router): void {
  // Idempotent install (same HMR rationale as installCoreCommands).
  for (const name of DESK_COMMAND_NAMES) {
    commandRegistry.unregister(name)
  }

  commandRegistry.register<WindowOpenArgs>({
    name: 'window.open',
    title: 'Apri finestra',
    description:
      'Open a module as a floating window on the assistant desk (navigates to the assistant view first when needed). Singleton modules focus the existing window.',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: {
        module: { type: 'string', enum: Object.keys(MODULE_REGISTRY) },
        params: { type: 'object' }
      },
      required: ['module']
    },
    run: async ({ module, params }) => {
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push({ name: 'assistant' })
      }
      const id = useDeskStore().openWindow(module, params)
      if (id === null) throw new Error(`Unknown module: ${module}`)
      return { window_id: id }
    }
  })

  commandRegistry.register<WindowIdArgs>({
    name: 'window.focus',
    title: 'Porta in primo piano',
    description: 'Bring a desk window to the front (restores it when minimized)',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { window_id: { type: 'string' } },
      required: ['window_id']
    },
    run: ({ window_id }) => {
      if (!useDeskStore().focusWindow(window_id)) {
        throw new Error(`Unknown window: ${window_id}`)
      }
    }
  })

  commandRegistry.register({
    name: 'window.list',
    title: 'Elenca finestre',
    description:
      'List the desk windows with id, module, title, geometry, minimized and focused flags',
    exposeToAgent: true,
    capability: 'read',
    argsSchema: { type: 'object', properties: {} },
    run: () => ({ windows: useDeskStore().listWindows() })
  })

  commandRegistry.register<WindowIdArgs>({
    name: 'window.close',
    title: 'Chiudi finestra',
    description:
      'Close a desk window (visibility only: the underlying module state is never destroyed)',
    exposeToAgent: true,
    capability: 'mutate',
    argsSchema: {
      type: 'object',
      properties: { window_id: { type: 'string' } },
      required: ['window_id']
    },
    run: ({ window_id }) => {
      if (!useDeskStore().closeWindow(window_id)) {
        throw new Error(`Unknown window: ${window_id}`)
      }
    }
  })

  commandRegistry.register<WindowArrangeArgs>({
    name: 'window.arrange',
    title: 'Disponi finestre',
    description: 'Arrange the non-minimized desk windows with a preset (cascade or tile)',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { preset: { type: 'string', enum: ['cascade', 'tile'] } },
      required: ['preset']
    },
    run: ({ preset }) => {
      useDeskStore().arrangeWindows(preset)
    }
  })
}
```

- [ ] **Step 3.4: Barrel + install in App.vue**

In `commands/index.ts` aggiungere:

```ts
export { installDeskCommands, DESK_COMMAND_NAMES } from './desk'
export type { WindowOpenArgs, WindowIdArgs, WindowArrangeArgs } from './desk'
```

In `App.vue`, riga import (16): `import { installCoreCommands, installDeskCommands } from './commands'` e dopo la riga 33 (`installCoreCommands(router)`):

```ts
installDeskCommands(router)
```

- [ ] **Step 3.5: Verificare che passi**

Run: `npx vitest run src/renderer/src/commands/desk.spec.ts`
Expected: PASS.

- [ ] **Step 3.6: Typecheck + commit**

```powershell
npm run typecheck
git add src/renderer/src/commands/ src/renderer/src/App.vue
git commit -m "feat(desk): agent-facing window.* commands on the command bridge"
```

---

### Task 4: Modulo Attività (+ icona)

**Files:**
- Modify: `frontend/src/renderer/src/assets/icons.ts` (nuova voce `pulse`)
- Create: `frontend/src/renderer/src/components/workspace/modules/ActivityModule.vue`
- Modify: `frontend/src/renderer/src/composables/workspace/moduleRegistry.ts` (voce `activity`)

- [ ] **Step 4.1: Icona**

In `assets/icons.ts`, accanto alle altre voci solar (es. dopo `'bar-chart'`, riga ~300), aggiungere:

```ts
  /** Agent activity (tools / subagents) */
  pulse: { icon: 'solar:pulse-bold' },
```

(se una voce `pulse` esiste già, riusarla e saltare questo step).

- [ ] **Step 4.2: ActivityModule**

```vue
<!-- components/workspace/modules/ActivityModule.vue -->
<script setup lang="ts">
/**
 * ActivityModule — the agent's full activity detail: per-turn tool calls,
 * interactions, token usage (agentRun store) and running background tasks /
 * subagents (backgroundTasks store). Read-only observability surface.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * none — the module always follows the current run.
 */
import { computed } from 'vue'
import { useAgentRunStore } from '../../../stores/agentRun'
import { useBackgroundTasksStore } from '../../../stores/backgroundTasks'
import AppIcon from '../../ui/AppIcon.vue'
import AliceSpinner from '../../ui/AliceSpinner.vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'

defineProps<{
  params?: Record<string, unknown>
}>()

const agentRun = useAgentRunStore()
const backgroundTasks = useBackgroundTasksStore()

const run = computed(() => agentRun.currentRun)

/** Tools + interactions merged in arrival order (both carry `seq`). */
const activities = computed(() => {
  const r = run.value
  if (r === null) return []
  return [
    ...r.tools.map((t) => ({ type: 'tool' as const, seq: t.seq, tool: t })),
    ...r.interactions.map((i) => ({ type: 'interaction' as const, seq: i.seq, interaction: i }))
  ].sort((a, b) => a.seq - b.seq)
})

const isEmpty = computed(() => run.value === null && backgroundTasks.active.length === 0)

function argsSummary(args: Record<string, unknown>): string {
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? `${s.slice(0, 77)}…` : s
  } catch {
    return ''
  }
}
</script>

<template>
  <div class="activity-module">
    <UiEmptyState
      v-if="isEmpty"
      icon="pulse"
      title="Nessuna attività"
      subtitle="I tool e i subagent del turno appariranno qui"
      compact
    />

    <template v-else>
      <div v-if="run" class="activity-module__meta">
        <span v-if="run.maxSteps > 0">passo {{ run.step }}/{{ run.maxSteps }}</span>
        <span v-else-if="run.step > 0">passo {{ run.step }}</span>
        <span>{{ run.toolCalls }} tool</span>
        <span>{{ (run.inputTokens + run.outputTokens).toLocaleString('it-IT') }} token</span>
        <span v-if="run.status === 'finished'" class="activity-module__done">concluso</span>
      </div>

      <ul v-if="activities.length > 0" class="activity-module__list">
        <li v-for="a in activities" :key="`${a.type}-${a.seq}`" class="activity-module__row">
          <template v-if="a.type === 'tool'">
            <AliceSpinner v-if="a.tool.status === 'running'" :size="12" />
            <AppIcon
              v-else
              :name="a.tool.status === 'success' ? 'check' : 'circle-x'"
              :size="12"
              :class="
                a.tool.status === 'success'
                  ? 'activity-module__ok'
                  : 'activity-module__err'
              "
            />
            <span class="activity-module__name">{{ a.tool.toolName.replace(/_/g, ' ') }}</span>
            <span class="activity-module__args">{{ argsSummary(a.tool.args) }}</span>
          </template>
          <template v-else>
            <AppIcon name="help-circle" :size="12" />
            <span class="activity-module__name">{{ a.interaction.kind }}</span>
            <span class="activity-module__args">{{
              a.interaction.status === 'pending' ? 'in attesa…' : (a.interaction.outcome ?? '')
            }}</span>
          </template>
        </li>
      </ul>

      <section v-if="backgroundTasks.active.length > 0" class="activity-module__bg">
        <h3 class="activity-module__bg-title">In background</h3>
        <ul class="activity-module__list">
          <li v-for="t in backgroundTasks.active" :key="t.task_id" class="activity-module__row">
            <AliceSpinner :size="12" />
            <span class="activity-module__name">{{ t.title ?? t.kind ?? t.task_id }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.activity-module {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.activity-module__meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.activity-module__done {
  color: var(--state-success);
}

.activity-module__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}

.activity-module__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  min-width: 0;
}

.activity-module__name {
  color: var(--text-primary);
  flex: none;
}

.activity-module__args {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-module__ok {
  color: var(--state-success);
}

.activity-module__err {
  color: var(--state-danger);
}

.activity-module__bg-title {
  margin: 0 0 var(--space-1-5);
  font-size: var(--text-2xs);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: var(--weight-medium);
}
</style>
```

Nota: verificare i nomi icona `check`, `circle-x`, `help-circle` in `assets/icons.ts` (`circle-x` esiste, riga ~238); se `check`/`help-circle` mancano, sostituirli con equivalenti registrati (grep `check` / `question` nel file) — mai stringhe iconify inline.

Nota: `t.title ?? t.kind` — verificare i campi reali di `WsBackgroundTaskUpdated` in `types/generated` e adeguare (il fallback `t.task_id` resta).

- [ ] **Step 4.3: Registrare il modulo**

In `moduleRegistry.ts`, dopo la definizione `terminal` (riga ~96):

```ts
const activity: ModuleDef = {
  id: 'activity',
  label: 'Attività',
  icon: 'pulse',
  component: () => import('../../components/workspace/modules/ActivityModule.vue'),
  defaultZone: 'right',
  singleton: true
}
```

e aggiungere `activity` a `MODULE_REGISTRY`.

- [ ] **Step 4.4: Gate + commit**

```powershell
npm run typecheck
npx vitest run
git add src/renderer/src/assets/icons.ts src/renderer/src/components/workspace/modules/ActivityModule.vue src/renderer/src/composables/workspace/moduleRegistry.ts
git commit -m "feat(modules): Attivita module (agentRun + backgroundTasks) in the shared catalog"
```

(Il modulo appare automaticamente anche nei launcher del Workspace: comportamento voluto, spec §4.1.)

---

### Task 5: `useWindowInteractions` — drag e resize

**Files:**
- Create: `frontend/src/renderer/src/composables/desk/useWindowInteractions.ts`

Niente unit test (pointer events; la matematica è già coperta da deskGeometry.spec) — coerente con la cultura test del repo (spec-only sui moduli puri).

- [ ] **Step 5.1: Implementazione**

```ts
// composables/desk/useWindowInteractions.ts
/**
 * useWindowInteractions — pointer-driven drag (header) and resize (grips)
 * for one desk window. All geometry math lives in deskGeometry via the desk
 * store's clamped move/resize actions; this composable only tracks pointers.
 *
 * While a drag/resize session is active the store's draggingId is set, so
 * external (agent) geometry mutations on the same window are ignored
 * (spec §6.10 — user interaction wins).
 */
import { useDeskStore } from '../../stores/desk'
import type { DeskRect } from './deskGeometry'

export type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

export function useWindowInteractions(windowId: string): {
  startDrag: (e: PointerEvent) => void
  startResize: (edge: ResizeEdge, e: PointerEvent) => void
} {
  const desk = useDeskStore()

  function _session(
    e: PointerEvent,
    onMove: (dx: number, dy: number) => void
  ): void {
    if (e.button !== 0) return
    const el = e.currentTarget as HTMLElement
    const startX = e.clientX
    const startY = e.clientY
    desk.setDragging(windowId)
    el.setPointerCapture(e.pointerId)

    const move = (ev: PointerEvent): void => {
      onMove(ev.clientX - startX, ev.clientY - startY)
    }
    const end = (): void => {
      desk.setDragging(null)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', end)
      el.removeEventListener('pointercancel', end)
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', end)
    el.addEventListener('pointercancel', end)
    e.preventDefault()
  }

  function startDrag(e: PointerEvent): void {
    // Header buttons must stay buttons, not drag handles.
    if ((e.target as HTMLElement | null)?.closest('button') !== null) return
    const win = desk.windows.find((w) => w.id === windowId)
    if (win === undefined) return
    desk.focusWindow(windowId)
    const start = { ...win.rect }
    _session(e, (dx, dy) => {
      desk.moveWindow(windowId, start.x + dx, start.y + dy)
    })
  }

  function startResize(edge: ResizeEdge, e: PointerEvent): void {
    const win = desk.windows.find((w) => w.id === windowId)
    if (win === undefined) return
    desk.focusWindow(windowId)
    const start: DeskRect = { ...win.rect }
    _session(e, (dx, dy) => {
      const r: DeskRect = { ...start }
      if (edge.includes('e')) r.w = start.w + dx
      if (edge.includes('s')) r.h = start.h + dy
      if (edge.includes('w')) {
        r.x = start.x + dx
        r.w = start.w - dx
      }
      if (edge.includes('n')) {
        r.y = start.y + dy
        r.h = start.h - dy
      }
      desk.resizeWindow(windowId, r)
    })
  }

  return { startDrag, startResize }
}
```

- [ ] **Step 5.2: Gate + commit**

```powershell
npm run typecheck
git add src/renderer/src/composables/desk/useWindowInteractions.ts
git commit -m "feat(desk): pointer drag/resize composable"
```

---

### Task 6: `DeskWindow.vue` — il foglio

**Files:**
- Create: `frontend/src/renderer/src/components/desk/DeskWindow.vue`

- [ ] **Step 6.1: Implementazione**

```vue
<!-- components/desk/DeskWindow.vue -->
<script setup lang="ts">
/**
 * DeskWindow — the atelier "sheet": floating window chrome around a catalog
 * module (same MODULE_REGISTRY as the Workspace tiles, different dress).
 * Geometry/z/focus live in the desk store; this component renders one window
 * and wires drag (header) + resize (grips).
 *
 * Minimized windows are hidden with v-show (NOT unmounted) so live module
 * views (xterm, canvases) survive the round-trip to the dock.
 */
import { computed, defineAsyncComponent, h } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import AliceSpinner from '../ui/AliceSpinner.vue'
import { useDeskStore } from '../../stores/desk'
import { getModule } from '../../composables/workspace/moduleRegistry'
import { useWindowInteractions } from '../../composables/desk/useWindowInteractions'
import type { ResizeEdge } from '../../composables/desk/useWindowInteractions'
import type { DeskWindowState } from '../../composables/desk/deskGeometry'

const props = defineProps<{
  win: DeskWindowState
}>()

const desk = useDeskStore()
const { startDrag, startResize } = useWindowInteractions(props.win.id)

const EDGES: ResizeEdge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

const moduleDef = computed(() => getModule(props.win.moduleId))
const title = computed(() => moduleDef.value?.label ?? props.win.moduleId)
const focused = computed(() => desk.focusedId === props.win.id)

// Lazy adapter resolution — PanelLeaf's pattern + retry-then-fail on load
// errors (spec §6.16: a failed chunk must not crash the scene).
const asyncComp = computed(() => {
  const def = moduleDef.value
  if (def === undefined) return null
  return defineAsyncComponent({
    loader: def.component,
    loadingComponent: AliceSpinner,
    errorComponent: {
      render: () =>
        h(UiEmptyState, {
          icon: 'alert-triangle',
          title: 'Modulo non caricato',
          subtitle: 'Chiudi e riapri la finestra',
          compact: true
        })
    },
    onError(_error, retry, fail, attempts) {
      if (attempts <= 2) retry()
      else fail()
    }
  })
})

const styleObj = computed(() => ({
  left: `${props.win.rect.x}px`,
  top: `${props.win.rect.y}px`,
  width: `${props.win.rect.w}px`,
  height: `${props.win.rect.h}px`,
  zIndex: props.win.z + 1
}))

function onWindowPointerDown(): void {
  if (!focused.value) desk.focusWindow(props.win.id)
}
</script>

<template>
  <section
    v-show="!win.minimized"
    class="desk-window"
    :class="{ 'desk-window--focused': focused }"
    :style="styleObj"
    role="region"
    :aria-label="title"
    @pointerdown="onWindowPointerDown"
  >
    <header class="desk-window__header" @pointerdown="startDrag">
      <AppIcon v-if="moduleDef" :name="moduleDef.icon" :size="13" class="desk-window__icon" />
      <span class="desk-window__title">{{ title }}</span>
      <UiIconButton
        label="Riduci nel vassoio"
        size="xs"
        variant="ghost"
        @click="desk.minimizeWindow(win.id)"
      >
        <AppIcon name="minus" :size="12" />
      </UiIconButton>
      <UiIconButton label="Chiudi finestra" size="xs" variant="ghost" @click="desk.closeWindow(win.id)">
        <AppIcon name="x" :size="12" />
      </UiIconButton>
    </header>

    <div class="desk-window__body">
      <component :is="asyncComp" v-if="asyncComp" :params="win.params" />
      <UiEmptyState
        v-else
        icon="alert-triangle"
        title="Modulo non disponibile"
        :subtitle="`«${win.moduleId}» non è registrato`"
        compact
      />
    </div>

    <span
      v-for="edge in EDGES"
      :key="edge"
      class="desk-window__grip"
      :class="`desk-window__grip--${edge}`"
      aria-hidden="true"
      @pointerdown="(e) => startResize(edge, e)"
    />
  </section>
</template>

<style scoped>
/* Atelier sheet: theme tokens only (dual-theme by construction). */
.desk-window {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  overflow: hidden;
  pointer-events: auto;
}

.desk-window--focused {
  border-color: var(--border-hover);
  box-shadow: var(--shadow-elevated);
}

.desk-window__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  flex: none;
  padding: 0 var(--space-2);
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.desk-window__header:active {
  cursor: grabbing;
}

.desk-window__icon {
  color: var(--text-secondary);
  flex: none;
}

.desk-window__title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.desk-window__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.desk-window__body > * {
  flex: 1;
  min-height: 0;
}

/* Resize grips: invisible strips along edges/corners. */
.desk-window__grip {
  position: absolute;
  touch-action: none;
}

.desk-window__grip--n,
.desk-window__grip--s {
  left: 10px;
  right: 10px;
  height: 6px;
  cursor: ns-resize;
}

.desk-window__grip--n {
  top: -3px;
}

.desk-window__grip--s {
  bottom: -3px;
}

.desk-window__grip--e,
.desk-window__grip--w {
  top: 10px;
  bottom: 10px;
  width: 6px;
  cursor: ew-resize;
}

.desk-window__grip--e {
  right: -3px;
}

.desk-window__grip--w {
  left: -3px;
}

.desk-window__grip--ne,
.desk-window__grip--nw,
.desk-window__grip--se,
.desk-window__grip--sw {
  width: 12px;
  height: 12px;
}

.desk-window__grip--ne {
  top: -3px;
  right: -3px;
  cursor: nesw-resize;
}

.desk-window__grip--nw {
  top: -3px;
  left: -3px;
  cursor: nwse-resize;
}

.desk-window__grip--se {
  bottom: -3px;
  right: -3px;
  cursor: nwse-resize;
}

.desk-window__grip--sw {
  bottom: -3px;
  left: -3px;
  cursor: nesw-resize;
}
</style>
```

- [ ] **Step 6.2: Gate + commit**

```powershell
npm run typecheck
git add src/renderer/src/components/desk/DeskWindow.vue
git commit -m "feat(desk): atelier window chrome (drag, resize, focus, lazy module body)"
```

---

### Task 7: `DeskSurface.vue` + `DeskDock.vue`

**Files:**
- Create: `frontend/src/renderer/src/components/desk/DeskSurface.vue`
- Create: `frontend/src/renderer/src/components/desk/DeskDock.vue`

- [ ] **Step 7.1: DeskSurface**

```vue
<!-- components/desk/DeskSurface.vue -->
<script setup lang="ts">
/**
 * DeskSurface — the windows layer of the Horizon desk. Renders every desk
 * window, measures the viewport for geometry clamping, and (while mounted)
 * consumes open-module intents — the same bus PanelWorkspace consumes on
 * /workspace; the two surfaces live on different routes so exactly one
 * subscriber is active at a time.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import DeskWindow from './DeskWindow.vue'
import { useDeskStore } from '../../stores/desk'
import { onOpenModule } from '../../composables/workspace/moduleIntents'

const desk = useDeskStore()
const surfaceEl = ref<HTMLElement | null>(null)

let unsubscribe: (() => void) | null = null
let observer: ResizeObserver | null = null

onMounted(() => {
  unsubscribe = onOpenModule((intent) => {
    desk.openWindow(intent.moduleId, intent.params)
  })
  if (surfaceEl.value !== null) {
    observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box !== undefined) desk.setViewport(Math.round(box.width), Math.round(box.height))
    })
    observer.observe(surfaceEl.value)
  }
})

onBeforeUnmount(() => {
  unsubscribe?.()
  observer?.disconnect()
})
</script>

<template>
  <div
    ref="surfaceEl"
    class="desk-surface"
    :class="{ 'desk-surface--interacting': desk.draggingId !== null }"
  >
    <DeskWindow v-for="w in desk.windows" :key="w.id" :win="w" />
  </div>
</template>

<style scoped>
.desk-surface {
  position: absolute;
  inset: 0;
  z-index: 4; /* above the scene zones (1-3), below the dock and overlays */
  pointer-events: none; /* windows re-enable their own */
}

.desk-surface--interacting {
  user-select: none;
}
</style>
```

- [ ] **Step 7.2: DeskDock**

```vue
<!-- components/desk/DeskDock.vue -->
<script setup lang="ts">
/**
 * DeskDock — the atelier tray: one launcher per available catalog module,
 * open/minimized state dots, the Attività badge (running subagents +
 * background tasks) and the compact plan chip. Every action goes through the
 * desk store — the same implementations the agent's window.* commands call.
 */
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { listModules } from '../../composables/workspace/moduleRegistry'
import { useDeskStore } from '../../stores/desk'
import { useChatStore } from '../../stores/chat'
import { useTasksStore } from '../../stores/tasks'
import { useBackgroundTasksStore } from '../../stores/backgroundTasks'
import { planView } from '../../composables/horizon/horizonScene'

const desk = useDeskStore()
const chatStore = useChatStore()
const tasksStore = useTasksStore()
const backgroundTasks = useBackgroundTasksStore()

const modules = computed(() =>
  listModules().filter(
    (m) => m.available?.({ conversationId: chatStore.currentConversation?.id ?? null }) ?? true
  )
)

const activityCount = computed(() => backgroundTasks.active.length)

const plan = computed(() => {
  const id = chatStore.currentConversation?.id
  return planView(id ? tasksStore.tasksFor(id) : [])
})

function stateOf(moduleId: string): 'open' | 'minimized' | 'none' {
  const s = desk.openByModule[moduleId]
  if (s === undefined) return 'none'
  if (s.open > 0) return 'open'
  if (s.minimized > 0) return 'minimized'
  return 'none'
}
</script>

<template>
  <nav class="desk-dock" aria-label="Vassoio moduli">
    <span v-for="m in modules" :key="m.id" class="desk-dock__slot">
      <UiIconButton
        :label="m.label"
        size="sm"
        variant="ghost"
        :active="stateOf(m.id) === 'open'"
        @click="desk.openWindow(m.id)"
      >
        <AppIcon :name="m.icon" :size="15" />
      </UiIconButton>
      <span
        v-if="stateOf(m.id) !== 'none'"
        class="desk-dock__dot"
        :class="{ 'desk-dock__dot--minimized': stateOf(m.id) === 'minimized' }"
        aria-hidden="true"
      />
      <span v-if="m.id === 'activity' && activityCount > 0" class="desk-dock__badge">
        {{ activityCount }}
      </span>
    </span>

    <button
      v-if="plan.total > 0"
      class="desk-dock__plan"
      type="button"
      :aria-label="`Apri il piano (${plan.completed} di ${plan.total} completati)`"
      @click="desk.openWindow('plan')"
    >
      PIANO {{ plan.completed }}/{{ plan.total }}
    </button>
  </nav>
</template>

<style scoped>
.desk-dock {
  position: absolute;
  bottom: clamp(40px, 6vh, 56px);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1-5) var(--space-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  z-index: 5;
}

.desk-dock__slot {
  position: relative;
  display: inline-flex;
}

.desk-dock__dot {
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--accent);
}

.desk-dock__dot--minimized {
  background: var(--border-hover);
}

.desk-dock__badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 14px;
  height: 14px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  color: var(--text-on-accent);
  background: var(--accent);
  border-radius: var(--radius-pill);
}

.desk-dock__plan {
  margin-left: var(--space-1-5);
  border: none;
  background: transparent;
  padding: 0 var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.14em;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out);
}

.desk-dock__plan:hover {
  color: var(--text-primary);
}
</style>
```

- [ ] **Step 7.3: Gate + commit**

```powershell
npm run typecheck
git add src/renderer/src/components/desk/
git commit -m "feat(desk): windows surface (intents + viewport) and dock tray"
```

---

### Task 8: Estrazione composable da HorizonView (additiva)

**Files:**
- Create: `frontend/src/renderer/src/composables/horizon/useHorizonKeyboard.ts`
- Create: `frontend/src/renderer/src/composables/horizon/useHorizonVoiceBridge.ts`

Logica **salvata** da `HorizonView.vue` (righe 274-302 e 304-376 attuali), con due evoluzioni da spec: la Esc-chain rilascia il focus finestra (mai chiude) e l'entrata Jarvis ignora i keydown originati dentro finestre/dock.

- [ ] **Step 8.1: useHorizonKeyboard**

```ts
// composables/horizon/useHorizonKeyboard.ts
/**
 * useHorizonKeyboard — global key capture for the Horizon desk.
 *
 * Esc walks the interrupt chain: TTS → streaming → composer → focused
 * window (focus release only — Esc NEVER closes windows, spec §6.9).
 * Any printable first character materializes the composer (Jarvis entry),
 * unless the keystroke originates inside an input, a dialog, a desk window
 * or the dock (spec §6.7 — typing in the terminal must stay in the terminal).
 */
import { onBeforeUnmount, onMounted } from 'vue'
import type { Ref } from 'vue'

export interface HorizonKeyboardDeps {
  /** A global modal owns the keyboard (useModal state). */
  modalVisible: () => boolean
  /** A pending confirmation / ask_user owns the keyboard. */
  sceneDimmed: () => boolean
  composerActive: Ref<boolean>
  isSpeaking: () => boolean
  isStreaming: () => boolean
  cancelSpeak: () => void
  stopGeneration: () => void
  seedComposer: (ch: string) => void
  hasFocusedWindow: () => boolean
  blurWindows: () => void
}

export function useHorizonKeyboard(deps: HorizonKeyboardDeps): void {
  function onGlobalKeydown(e: KeyboardEvent): void {
    if (e.isComposing) return
    if (deps.modalVisible()) return
    if (deps.sceneDimmed()) return
    if (e.key === 'Escape') {
      if (deps.isSpeaking()) deps.cancelSpeak()
      else if (deps.isStreaming()) deps.stopGeneration()
      else if (deps.composerActive.value) deps.composerActive.value = false
      else if (deps.hasFocusedWindow()) deps.blurWindows()
      return
    }
    if (deps.composerActive.value) return
    const tgt = e.target as HTMLElement | null
    if (
      tgt?.closest(
        'input, textarea, select, button, [contenteditable="true"], [role="dialog"], .desk-window, .desk-dock'
      )
    )
      return
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault()
      deps.composerActive.value = true
      deps.seedComposer(e.key)
    }
  }

  onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
}
```

- [ ] **Step 8.2: useHorizonVoiceBridge**

```ts
// composables/horizon/useHorizonVoiceBridge.ts
/**
 * useHorizonVoiceBridge — voice wiring salvaged from the monolithic
 * HorizonView: STT transcript routing (auto-send vs confirm-in-composer)
 * and TTS auto-speak when a stream completes.
 */
import { watch } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useVoiceStore } from '../../stores/voice'

export interface HorizonVoiceBridgeDeps {
  send: (
    content: string,
    conversationId?: string,
    files?: File[],
    opts?: { source?: string }
  ) => Promise<unknown>
  /** Materialize the composer pre-seeded with the transcript. */
  activateComposer: (seed: string) => void
  speak: (text: string) => void
}

export function useHorizonVoiceBridge(deps: HorizonVoiceBridgeDeps): void {
  const chatStore = useChatStore()
  const voiceStore = useVoiceStore()

  // STT transcript: auto-send by default; with "Conferma trascrizione" on,
  // the transcript lands in the composer instead.
  watch(
    () => voiceStore.transcript,
    (text) => {
      if (!text.trim()) return
      const spoken = text.trim()
      voiceStore.clearTranscript()
      if (voiceStore.confirmTranscript) {
        deps.activateComposer(spoken)
      } else {
        deps.send(spoken, undefined, undefined, { source: 'voice' }).catch(console.error)
      }
    }
  )

  // TTS auto-speak when streaming completes.
  let wasStreamingHere = false
  watch(
    () => chatStore.isStreamingCurrentConversation,
    (streaming) => {
      if (streaming) {
        wasStreamingHere = true
        return
      }
      if (!wasStreamingHere) return
      wasStreamingHere = false
      if (!voiceStore.autoTtsResponse || !voiceStore.ttsAvailable || !voiceStore.connected) return
      const msgs = chatStore.messages
      let lastUserIdx = -1
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'user') {
          lastUserIdx = i
          break
        }
      }
      const allContent = msgs
        .slice(lastUserIdx + 1)
        .filter((m) => m.role === 'assistant' && m.content.trim())
        .map((m) => m.content.trim())
        .join('\n')
      if (allContent) deps.speak(allContent)
    }
  )
}
```

- [ ] **Step 8.3: Gate + commit**

```powershell
npm run typecheck
git add src/renderer/src/composables/horizon/useHorizonKeyboard.ts src/renderer/src/composables/horizon/useHorizonVoiceBridge.ts
git commit -m "refactor(horizon): extract keyboard and voice wiring into composables"
```

---

### Task 9: Lo swap atomico — scena atelier con desk

Questa task cambia il contratto della scena (via `presenting`) e sostituisce la vista: va committata come un unico cambiamento coerente. Ordine interno: prima i test della scena, poi i sorgenti, poi la vista, infine le rimozioni.

**Files:**
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.ts`
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.spec.ts`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonScene.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonLine.vue`
- Rewrite: `frontend/src/renderer/src/views/HorizonView.vue`
- Delete: `frontend/src/renderer/src/components/horizon/HorizonStage.vue`, `HorizonShelf.vue`, `HorizonHistory.vue`

- [ ] **Step 9.1: Aggiornare `horizonScene.spec.ts`**

Aprire la spec esistente e: rimuovere ogni test che passa `stageOpen`/`artifactCount` o si aspetta `'presenting'`; aggiornare le fixture di `HorizonSceneInputs` togliendo i due campi. Aggiungere il test:

```ts
it('never returns presenting: windows are orthogonal to the scene', () => {
  const state = deriveSceneState({
    isListening: false,
    isSttProcessing: false,
    isSpeaking: false,
    isStreaming: false,
    activeToolCount: 0,
    planSteps: [],
    composerActive: false
  })
  expect(state).toBe('quiet')
})
```

Run: `npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts` → FAIL (i tipi non compilano ancora).

- [ ] **Step 9.2: `horizonScene.ts`**

Modifiche puntuali:
- `export type HorizonState = 'quiet' | 'listening' | 'responding' | 'working'`
- In `HorizonSceneInputs` eliminare `stageOpen: boolean` e `artifactCount: number`.
- In `deriveSceneState` eliminare la riga `if (i.stageOpen && i.artifactCount > 0) return 'presenting'`.
- `deriveLineMode` resta invariato (lo switch non cita `presenting`).
- `notchPositions`, `planView` invariati. `toRoman` e `artifactLabel` (in `horizonArtifacts.ts`) si toccano nella Task 10, non qui.

- [ ] **Step 9.3: `HorizonScene.vue`**

Togliere la chiave `presenting: 0.26` da `QUOTAS` (riga 27). Il tipo `Record<HorizonState, number>` ora compila esattamente con le 4 chiavi.

- [ ] **Step 9.4: `HorizonLine.vue` — rimuovere `attenuated`**

Quattro edit puntuali:
- riga 34: eliminare `attenuated?: boolean`
- riga 44: eliminare `attenuated: false,`
- riga 97: `const alpha = props.dimmed ? 0.35 : 1`
- riga 128: sostituire `(props.attenuated ? 0.5 : 1.5)` con `1.5`
- riga 285: togliere `props.attenuated,` dalla lista del watch

- [ ] **Step 9.5: Riscrivere `HorizonView.vue`**

```vue
<!-- views/HorizonView.vue -->
<script setup lang="ts">
/**
 * HorizonView — the assistant desk ("atelier"): the ambient scene (greeting,
 * composer, paced response, horizon line) with free-floating module windows
 * (DeskSurface) and the tray (DeskDock) above it. Orchestration only — the
 * heavy wiring lives in useHorizonKeyboard / useHorizonVoiceBridge and the
 * desk store; scene derivation stays in the pure horizonScene brain.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import HorizonPlan from '../components/horizon/HorizonPlan.vue'
import HorizonScene from '../components/horizon/HorizonScene.vue'
import HorizonLine from '../components/horizon/HorizonLine.vue'
import HorizonMasthead from '../components/horizon/HorizonMasthead.vue'
import HorizonQuiet from '../components/horizon/HorizonQuiet.vue'
import HorizonColophon from '../components/horizon/HorizonColophon.vue'
import HorizonCockpit from '../components/horizon/HorizonCockpit.vue'
import HorizonComposer from '../components/horizon/HorizonComposer.vue'
import HorizonResponse from '../components/horizon/HorizonResponse.vue'
import DeskSurface from '../components/desk/DeskSurface.vue'
import DeskDock from '../components/desk/DeskDock.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import AskUserPrompt from '../components/chat/AskUserPrompt.vue'
import { ChatApiKey } from '../composables/useChat'
import { useSentencePacer } from '../composables/horizon/useSentencePacer'
import { useHorizonKeyboard } from '../composables/horizon/useHorizonKeyboard'
import { useHorizonVoiceBridge } from '../composables/horizon/useHorizonVoiceBridge'
import { useVoice } from '../composables/useVoice'
import { useModal } from '../composables/useModal'
import {
  deriveSceneState,
  deriveLineMode,
  planView,
  type HorizonSceneInputs
} from '../composables/horizon/horizonScene'
import { extractArtifacts } from '../composables/horizon/horizonArtifacts'
import { useGenerationState } from '../composables/useGenerationState'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import { useTasksStore } from '../stores/tasks'
import { useCalendarStore } from '../stores/calendar'
import { useDeskStore } from '../stores/desk'
import '../assets/styles/horizon.css'

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const tasksStore = useTasksStore()
const calendarStore = useCalendarStore()
const desk = useDeskStore()

const chatApi = inject(ChatApiKey, null)
const _noop = (): void => {}
const _asyncNoop = async (): Promise<void> => {}
const send = chatApi?.sendMessage ?? _asyncNoop
const stopGeneration = chatApi?.stopGeneration ?? _noop
const respondToConfirmation = chatApi?.respondToConfirmation ?? _noop
const answerAskUser = chatApi?.answerAskUser ?? _noop
const isConnected = chatApi?.isConnected ?? ref(false)

const {
  startListening,
  stopListening,
  cancelProcessing,
  connect: connectVoice,
  transcript,
  speak,
  cancelSpeak,
  audioDevices,
  selectedDeviceId,
  refreshDevices
} = useVoice()

const { cadGenerationInProgress } = useGenerationState()
const { state: modalState } = useModal()

/* ── local state ── */
const composerActive = ref(false)
const magazine = ref(false)
const composerRef = ref<InstanceType<typeof HorizonComposer> | null>(null)
const cockpitRef = ref<InstanceType<typeof HorizonCockpit> | null>(null)

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/* ── derived ── */
const planSteps = computed(() => {
  const id = chatStore.currentConversation?.id
  return id ? tasksStore.tasksFor(id) : []
})

const artifacts = computed(() => extractArtifacts(chatStore.messages))

const sceneInputs = computed<HorizonSceneInputs>(() => ({
  isListening: voiceStore.isListening,
  isSttProcessing: voiceStore.isProcessing,
  isSpeaking: voiceStore.isSpeaking,
  isStreaming: chatStore.isStreamingCurrentConversation,
  activeToolCount: chatStore.activeToolExecutions.length,
  planSteps: planSteps.value,
  composerActive: composerActive.value
}))

const sceneState = computed(() => deriveSceneState(sceneInputs.value))
const lineMode = computed(() => deriveLineMode(sceneState.value, sceneInputs.value))

const { displayed: pacedStream, reset: resetPacer } = useSentencePacer(
  computed(() => chatStore.currentStreamContent),
  computed(() => chatStore.isStreamingCurrentConversation),
  { immediate: reducedMotion }
)

const lastResponse = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

const lastUserQuery = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

const responseText = computed(() => {
  if (sceneState.value === 'responding') {
    return chatStore.isStreamingCurrentConversation ? pacedStream.value : lastResponse.value
  }
  if (sceneState.value === 'quiet') return lastResponse.value
  return ''
})

const showResponse = computed(
  () =>
    responseText.value !== '' &&
    (sceneState.value === 'responding' || (sceneState.value === 'quiet' && !composerActive.value))
)

const plan = computed(() => planView(planSteps.value))

const lineLabel = computed(() => {
  if (voiceStore.isListening) return 'ASCOLTO'
  if (voiceStore.isProcessing) return 'ELABORO'
  if (sceneState.value === 'working')
    return planSteps.value.length > 0
      ? `LAVORO ${plan.value.activeIndex + 1} DI ${plan.value.total}`
      : 'LAVORO'
  if (sceneState.value === 'responding') return 'RISPONDO'
  return ''
})

/* Ephemeral tool annotation (ambient sign; full detail = Attività window). */
const toolAnnotation = ref('')
let annotationTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => chatStore.activeToolExecutions.map((t) => t.toolName).join(','),
  () => {
    const tools = chatStore.activeToolExecutions
    const last = tools[tools.length - 1]
    if (!last) return
    toolAnnotation.value = last.toolName.replace(/_/g, ' ')
    if (annotationTimer) clearTimeout(annotationTimer)
    annotationTimer = setTimeout(() => {
      toolAnnotation.value = ''
    }, 2500)
  }
)

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))
const pendingAskUserList = computed(() => Object.values(chatStore.pendingAskUser))
const sceneDimmed = computed(
  () => pendingConfirmationsList.value.length > 0 || pendingAskUserList.value.length > 0
)

/* ── interactions ── */
/** Clicking empty desk space toggles voice — never windows, dock or overlays. */
function handleSceneClick(event: MouseEvent): void {
  if (sceneDimmed.value) return
  const tgt = event.target as HTMLElement | null
  if (
    tgt?.closest(
      'button, a, input, textarea, [contenteditable], .desk-window, .desk-dock, .hz-response'
    )
  )
    return
  if (voiceStore.isSpeaking) {
    cancelSpeak()
  } else if (chatStore.isStreamingCurrentConversation) {
    stopGeneration()
    cancelSpeak()
  } else if (voiceStore.isListening) {
    stopListening()
  } else if (voiceStore.isProcessing) {
    cancelProcessing()
  } else if (!composerActive.value) {
    startListening()
  }
}

async function handleComposerSend(content: string): Promise<void> {
  const files = cockpitRef.value ? [...cockpitRef.value.pendingFiles] : []
  cockpitRef.value?.clearAllFiles()
  composerActive.value = false
  await send(content, undefined, files.length > 0 ? files : undefined).catch(console.error)
}

function handleComposerPaste(e: ClipboardEvent): void {
  cockpitRef.value?.handlePaste(e)
}

function activateComposer(seed: string): void {
  composerActive.value = true
  composerRef.value?.seed(seed)
}

/** Materialize the ambient conversation into the chat window (singleton). */
function materializeConversation(): void {
  desk.openWindow('chat')
}

useHorizonKeyboard({
  modalVisible: () => modalState.visible,
  sceneDimmed: () => sceneDimmed.value,
  composerActive,
  isSpeaking: () => voiceStore.isSpeaking,
  isStreaming: () => chatStore.isStreamingCurrentConversation,
  cancelSpeak,
  stopGeneration,
  seedComposer: (ch) => composerRef.value?.seed(ch),
  hasFocusedWindow: () => desk.focusedId !== null,
  blurWindows: () => desk.blurWindows()
})

useHorizonVoiceBridge({ send, activateComposer, speak })

/* ── watchers ── */
// New turn: reset pacing + magazine.
watch(
  () => chatStore.isStreamingCurrentConversation,
  (streaming, was) => {
    if (streaming && !was) {
      resetPacer()
      magazine.value = false
    }
  }
)

// Conversation switch: pacing and layout never leak across conversations.
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    resetPacer()
    magazine.value = false
    if (id)
      tasksStore.ensureForConversation(id).catch(() => {
        /* timeline stays empty */
      })
  }
)

// A new artifact in a live turn opens its window (auto-open, spec §3.2).
watch(
  () => artifacts.value.length,
  (len, was) => {
    if (len > (was ?? 0) && chatStore.isStreamingCurrentConversation) {
      const a = artifacts.value[len - 1]
      if (a.kind === 'chart') desk.openWindow('chart', { chartPayload: a.chart })
      else if (a.kind === 'whiteboard') desk.openWindow('whiteboard', { boardId: a.board?.board_id })
      else desk.openWindow('cad3d')
    }
  }
)

// CAD generation surfaces its window once per generation (stable executionId).
watch(
  () => cadGenerationInProgress.value?.executionId,
  (id, old) => {
    if (id && id !== old) desk.openWindow('cad3d')
  }
)

/* ── lifecycle ── */
onMounted(() => {
  connectVoice()
  chatStore.restoreConversation().catch(console.error)
  calendarStore.startPolling()
  const id = chatStore.currentConversation?.id
  if (id) {
    tasksStore.ensureForConversation(id).catch(() => {
      /* timeline simply stays empty */
    })
  }
})

onBeforeUnmount(() => {
  calendarStore.stopPolling()
  if (annotationTimer) clearTimeout(annotationTimer)
})
</script>

<template>
  <div class="horizon-view" aria-label="Assistente" @click="handleSceneClick">
    <HorizonScene :state="sceneState" :magazine="magazine" :dimmed="sceneDimmed">
      <template #masthead>
        <HorizonMasthead :connected="isConnected" />
      </template>

      <template #upper>
        <Transition name="hz-soft">
          <HorizonQuiet v-if="sceneState === 'quiet' && !composerActive && !lastResponse" />
        </Transition>
        <HorizonComposer
          ref="composerRef"
          :active="composerActive"
          :listening="voiceStore.isListening"
          :stt-processing="voiceStore.isProcessing"
          :transcript="transcript"
          :disabled="chatStore.isStreamingCurrentConversation"
          @send="handleComposerSend"
          @paste="handleComposerPaste"
        />
        <Transition name="hz-soft">
          <HorizonCockpit
            v-if="composerActive"
            ref="cockpitRef"
            :is-streaming="chatStore.isStreamingCurrentConversation"
            :audio-devices="audioDevices"
            :selected-device-id="selectedDeviceId"
            @send="composerRef?.submit()"
            @stop="stopGeneration"
            @voice-start="startListening"
            @voice-stop="stopListening"
            @voice-cancel-processing="cancelProcessing"
            @refresh-devices="refreshDevices"
            @select-device="(id) => (selectedDeviceId = id)"
          />
        </Transition>
        <HorizonResponse
          v-if="showResponse && !magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="false"
        />
        <p v-if="sceneState === 'working' && plan.statusSentence" class="horizon-view__status">
          <em>{{ plan.statusSentence }}</em>
        </p>
      </template>

      <template #line>
        <HorizonLine
          :mode="lineMode"
          :audio-level="voiceStore.audioLevel"
          :notch-count="sceneState === 'working' ? planSteps.length : 0"
          :active-index="plan.activeIndex"
          :completed-count="plan.completed"
          :dimmed="!isConnected"
          :label="lineLabel"
        />
      </template>

      <template #lower>
        <HorizonPlan
          v-if="sceneState === 'working' && planSteps.length > 0"
          :steps="planSteps"
          :active-index="plan.activeIndex"
          :completed="plan.completed"
          :annotation="toolAnnotation"
        />
        <HorizonResponse
          v-if="showResponse && magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="false"
        />
        <p v-if="sceneState === 'responding' && lastUserQuery" class="horizon-view__echo">
          {{ lastUserQuery }}
        </p>
        <HorizonColophon :next-event="calendarStore.nextEvent" :connected="isConnected" />
      </template>
    </HorizonScene>

    <!-- The windows layer + tray (the desk) -->
    <DeskSurface />
    <DeskDock />

    <nav class="horizon-view__corner" aria-label="Navigazione">
      <button class="horizon-view__affordance" type="button" @click="materializeConversation">
        CONVERSAZIONE
      </button>
      <RouterLink class="horizon-view__affordance" :to="{ name: 'workspace' }">
        WORKSPACE
      </RouterLink>
    </nav>

    <ToolConfirmationDialog
      v-if="pendingConfirmationsList.length > 0"
      :key="pendingConfirmationsList[0].executionId"
      :confirmation="pendingConfirmationsList[0]"
      @respond="respondToConfirmation"
    />

    <!-- ask_user sits ABOVE the dimmed scene (pointer-events gate). -->
    <div v-if="pendingAskUserList.length > 0" class="horizon-view__ask">
      <AskUserPrompt
        v-for="r in pendingAskUserList"
        :key="r.executionId"
        :request="r"
        @answer="answerAskUser"
      />
    </div>
  </div>
</template>

<style scoped>
.horizon-view {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.horizon-view__ask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-5);
  overflow-y: auto;
  z-index: var(--z-overlay);
}

.horizon-view__ask > * {
  width: min(640px, 92%);
}

.hz-soft-enter-active,
.hz-soft-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-soft-enter-from,
.hz-soft-leave-to {
  opacity: 0;
}

.horizon-view__echo {
  margin: var(--space-3) 0 0;
  font-family: var(--font-sans);
  font-size: 10px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  max-width: 70%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.horizon-view__status {
  margin: 0 0 clamp(20px, 4vh, 48px);
  max-width: min(60ch, 80%);
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(17px, 2.4vmin, 24px);
  color: var(--hz-ink);
  text-align: center;
}

.horizon-view__corner {
  position: absolute;
  right: clamp(16px, 3vw, 32px);
  bottom: clamp(14px, 3vh, 28px);
  display: flex;
  gap: var(--space-4);
  z-index: var(--z-sticky);
}

.horizon-view__affordance {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  text-decoration: none;
  cursor: pointer;
  transition: color var(--hz-fade) ease;
}

.horizon-view__affordance:hover {
  color: var(--hz-ink);
}
</style>
```

Note di dettaglio:
- Spariscono: `historyOpen`, `stageOpen`, `stageIndex`, `planPinned`, `openArtifact`, `startEdit`/`handleVersionSwitch`/`handleBranch` (l'editing/branch vive nella finestra chat, che usa il ChatModule del Workspace), `MessageEditDialog` e `useModal.openCustom` (restano nel ChatModule), l'import di `HorizonStage`/`HorizonShelf`/`HorizonHistory`.
- `openCustom` non è più usato qui ma `modalState` sì (guard tastiera).
- L'evoluzione `HorizonResponse` `:compact` diventa sempre `false` (era legata a presenting): se il typecheck segnala la prop come richiesta, passarla esplicitamente com'è nel codice sopra.

- [ ] **Step 9.6: Eliminare i componenti sostituiti**

```powershell
git rm src/renderer/src/components/horizon/HorizonStage.vue src/renderer/src/components/horizon/HorizonShelf.vue src/renderer/src/components/horizon/HorizonHistory.vue
```

Poi verificare che nessun altro file li importi:

```powershell
Select-String -Path src -Pattern "HorizonStage|HorizonShelf|HorizonHistory" -Recurse
```

Expected: nessun risultato (solo la vista li importava).

- [ ] **Step 9.7: Gate completi**

```powershell
npx vitest run
npm run typecheck
npm run lint
```

Expected: tutto verde. Se `horizonScene.spec` o altri spec citano ancora `presenting`, correggerli qui.

- [ ] **Step 9.8: Commit**

```powershell
git add -A src/renderer/src
git commit -m "feat(horizon)!: atelier desk scene - floating windows, dock, ambient conversation"
```

---

### Task 10: Pulizia residui (orb, funzioni orfane)

**Files:**
- Modify: `frontend/src/renderer/src/assets/icons.ts` (rimuovere `orb`, righe 166-167)
- Modify: `frontend/src/renderer/src/components/sidebar/AppSidebar.vue:70`
- Modify: `frontend/src/renderer/src/components/chat/ChatInput.vue:42`
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.ts` (+spec) e `horizonArtifacts.ts` (+spec)

- [ ] **Step 10.1: Sostituire gli usi di `orb`**

- `AppSidebar.vue:70`: `{ value: 'assistant', label: 'Assistente', icon: 'orb' }` → `icon: 'pulse'`
- `ChatInput.vue:42`: `isOnWorkspace.value ? 'orb' : 'hybrid-panel'` → `isOnWorkspace.value ? 'pulse' : 'hybrid-panel'`
- Rimuovere la voce `orb` da `icons.ts` (righe 166-167).

Verifica: `Select-String -Path src -Pattern "'orb'" -Recurse` → nessun risultato.

- [ ] **Step 10.2: Funzioni orfane**

```powershell
Select-String -Path src -Pattern "toRoman|artifactLabel" -Recurse
```

Se (come atteso) gli unici usi residui sono definizione + spec: rimuovere `toRoman` da `horizonScene.ts` e `artifactLabel` da `horizonArtifacts.ts`, e i rispettivi blocchi `describe` dalle spec. Se emergono altri usi vivi, lasciarle e annotarlo nel commit.

- [ ] **Step 10.3: Gate + commit**

```powershell
npx vitest run
npm run typecheck
npm run lint
git add -A src/renderer/src
git commit -m "chore(frontend): drop orb icon leftovers and orphaned horizon helpers"
```

---

### Task 11: Verifica finale end-to-end

- [ ] **Step 11.1: Gate completi dal frontend**

```powershell
npx vitest run
npm run typecheck
npm run lint
```

Expected: tutti verdi.

- [ ] **Step 11.2: Verifica manuale nell'app viva** (skill `verify` / `run`; backend + frontend con `.\scripts\start-dev.ps1` dalla root)

Checklist (spec §10 — entrambe le voci tema dove sensato):
1. `/assistant` in quiete: saluto, linea in respiro, colophon; nessuna finestra.
2. Digitare un carattere → composer si materializza col seed; Esc lo dissolve.
3. Dock: aprire Grafico, Terminale, Attività → finestre in cascata; drag da header, resize da bordi/angoli; click porta in primo piano; minimizza → punto nel vassoio; riapri dal dock → torna alla geometria precedente.
4. Digitare DENTRO il terminale in finestra → il composer NON si materializza.
5. Esc con finestra focalizzata → rilascia il focus, la finestra resta aperta.
6. Chiedere in chat: «apri la finestra del grafico», «disponi le finestre affiancate», «chiudi la finestra del terminale» → l'agente usa `app_command`/`window.*`; in tier `plan` la chiusura viene negata.
7. Turno con piano → linea timeline + piano compatto + annotazione tool; finestra Attività mostra i tool in corso; badge sul dock con subagent attivi.
8. Generare un grafico → la finestra si apre da sola col payload.
9. «CONVERSAZIONE» nell'angolo → finestra chat con lo storico (edit/branch dentro la finestra).
10. Riavviare l'app → layout finestre ripristinato e clampato.
11. Tema chiaro: tutto leggibile, focus ring visibile su header/dock via tastiera.
12. Workspace: invariato, con in più il modulo Attività nel launcher.

- [ ] **Step 11.3: Commit finale (se la verifica ha prodotto fix) e chiusura**

Usare la skill superpowers:finishing-a-development-branch per merge/PR di `rework/horizon-atelier`.

---

## Self-review del piano (eseguita)

- **Copertura spec:** §3 scena/stati → Task 9; §3.3 meccanica → Task 1/2/5/6; §4.1 file → Task 1-8; §4.2 ricostruzione/estrazioni/rimozioni → Task 8/9/10; §5 comandi → Task 3; §6 edge case → clamp/migrazione (T1/T2), Jarvis-vs-finestre e Esc (T8), drag-vs-agente (T2/T5), singleton (T2), lazy-load error (T6), intents (T7), auto-open (T9), verifica manuale (T11). §8 testing → spec in T1/T2/T3 + gate ovunque.
- **Tipi coerenti:** `DeskWindowState`/`DeskRect` definiti in T1 e riusati identici in T2/T5/T6; `openWindow → string | null` coerente tra store, comandi e test; `focusedId`/`blurWindows` coerenti tra store, tastiera e vista.
- **Nessun placeholder:** ogni step con codice mostra il codice; i due punti di verifica nomi-icona/campi-WS in T4 sono istruzioni operative precise (grep + sostituzione), non TODO.
