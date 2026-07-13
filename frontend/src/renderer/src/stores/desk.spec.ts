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
        {
          id: 'a',
          moduleId: 'chart',
          rect: { x: 1, y: 2, w: 400, h: 300 },
          z: 3,
          minimized: false
        },
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
