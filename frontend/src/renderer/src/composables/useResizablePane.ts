/**
 * useResizablePane — drag-to-resize composable for AL\CE panels.
 *
 * Encapsulates the mousedown / mousemove / mouseup listener lifecycle that
 * was previously duplicated in HybridView (left pane, normal delta) and
 * AssistantView (side panel, inverted delta).  The composable is intentionally
 * px-based and DOM-element-agnostic; callers convert px ↔ ratios if needed.
 *
 * @example
 * ```ts
 * const { size, isDragging, onMouseDown } = useResizablePane({
 *   axis: 'x',
 *   min: 220,
 *   max: 900,
 *   initial: 840,
 * })
 * ```
 */

import { onScopeDispose, ref, type Ref } from 'vue'

// ── Public types ──────────────────────────────────────────────────────────────

export interface ResizablePaneOptions {
  /** Drag axis: 'x' controls width, 'y' controls height. */
  axis: 'x' | 'y'
  /** Minimum size in px. */
  min: number
  /** Maximum size in px. */
  max: number
  /** Initial size in px (clamped to [min, max] on creation). */
  initial: number
  /**
   * When `true` the pane **grows** as the pointer moves toward the origin
   * (left for axis 'x', up for axis 'y').  Used for right-edge panels where
   * dragging the left border leftward increases the width.
   *
   * @default false
   */
  invert?: boolean
}

export interface ResizablePaneController {
  /** Current size in px, clamped to [min, max]. */
  size: Ref<number>
  /** `true` while a drag gesture is in progress. */
  isDragging: Ref<boolean>
  /**
   * Attach to the divider element's `@mousedown` handler.
   * Registers `document` mousemove/mouseup listeners for the duration of the
   * drag and cleans up automatically on mouseup.
   */
  onMouseDown: (e: MouseEvent) => void
  /**
   * Removes any in-flight document listeners immediately.
   * Called automatically by `onScopeDispose`; expose for callers that need
   * manual teardown (e.g. legacy `onBeforeUnmount` hooks).
   *
   * **Note:** this removes document listeners but does NOT reset `isDragging`.
   * Callers invoking `cleanup` mid-drag are responsible for resetting
   * `isDragging` themselves (e.g. `isDragging.value = false`).
   */
  cleanup: () => void
  /**
   * Programmatically set the size, clamped to [min, max].
   *
   * @param n - Desired size in px.
   */
  setSize: (n: number) => void
}

// ── Implementation ────────────────────────────────────────────────────────────

/**
 * Create a drag-to-resize controller for a single pane divider.
 *
 * @param options - Configuration for axis, bounds, initial size and direction.
 * @returns A {@link ResizablePaneController} with reactive `size`/`isDragging`
 *   refs and an `onMouseDown` handler to wire to the divider element.
 */
export function useResizablePane(options: ResizablePaneOptions): ResizablePaneController {
  const { axis, min, max, invert = false } = options

  if (import.meta.env.DEV && options.min > options.max) {
    console.warn(
      `[useResizablePane] min (${options.min}) > max (${options.max}); clamping will always yield max.`
    )
  }

  const clamp = (v: number): number => Math.min(max, Math.max(min, v))

  const size = ref<number>(clamp(options.initial))
  const isDragging = ref<boolean>(false)

  // Stable references kept so we can remove exactly the same listener objects.
  let onMove: ((e: MouseEvent) => void) | null = null
  let onUp: (() => void) | null = null

  function cleanup(): void {
    if (onMove) {
      document.removeEventListener('mousemove', onMove)
      onMove = null
    }
    if (onUp) {
      document.removeEventListener('mouseup', onUp)
      onUp = null
    }
  }

  function onMouseDown(e: MouseEvent): void {
    e.preventDefault()

    isDragging.value = true
    const startCoord = axis === 'x' ? e.clientX : e.clientY
    const startSize = size.value

    // Remove any previous listeners that may have leaked (safety guard).
    cleanup()

    onMove = (ev: MouseEvent): void => {
      const currentCoord = axis === 'x' ? ev.clientX : ev.clientY
      const delta = invert ? startCoord - currentCoord : currentCoord - startCoord
      size.value = clamp(startSize + delta)
    }

    onUp = (): void => {
      isDragging.value = false
      cleanup()
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  function setSize(n: number): void {
    size.value = clamp(n)
  }

  // Automatically remove document listeners when the owning component/scope
  // is torn down (covers mid-drag unmounts without requiring a manual
  // onBeforeUnmount call in the consuming component).
  onScopeDispose(() => {
    isDragging.value = false
    cleanup()
  })

  return { size, isDragging, onMouseDown, cleanup, setSize }
}
