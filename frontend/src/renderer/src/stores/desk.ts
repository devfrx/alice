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
