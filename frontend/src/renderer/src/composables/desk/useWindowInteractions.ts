// composables/desk/useWindowInteractions.ts
/**
 * useWindowInteractions — pointer-driven drag (header) and resize (grips)
 * for one desk window. All geometry math lives in deskGeometry via the desk
 * store's clamped move/resize actions; this composable only tracks pointers.
 *
 * While a drag/resize session is active the store's draggingId is set, so
 * external (agent) geometry mutations on the same window are ignored
 * (spec §6.10 — user interaction wins).
 *
 * West/north resize pins the opposite edge by pre-clamping to MIN_SIZE (the
 * store's clampRect clamps size and position independently).
 */
import { useDeskStore } from '../../stores/desk'
import { MIN_SIZE } from './deskGeometry'
import type { DeskRect } from './deskGeometry'

export type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

export function useWindowInteractions(windowId: string): {
  startDrag: (e: PointerEvent) => void
  startResize: (edge: ResizeEdge, e: PointerEvent) => void
} {
  const desk = useDeskStore()

  function _session(e: PointerEvent, onMove: (dx: number, dy: number) => void): void {
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
      el.removeEventListener('lostpointercapture', end)
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', end)
    el.addEventListener('pointercancel', end)
    el.addEventListener('lostpointercapture', end)
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
        // Clamp width first, then pin the RIGHT edge (start.x + start.w).
        r.w = Math.max(MIN_SIZE.w, start.w - dx)
        r.x = start.x + start.w - r.w
      }
      if (edge.includes('n')) {
        // Clamp height first, then pin the BOTTOM edge (start.y + start.h).
        r.h = Math.max(MIN_SIZE.h, start.h - dy)
        r.y = start.y + start.h - r.h
      }
      desk.resizeWindow(windowId, r)
    })
  }

  return { startDrag, startResize }
}
