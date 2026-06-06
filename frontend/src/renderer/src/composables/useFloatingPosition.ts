/**
 * useFloatingPosition — Trigger-anchored fixed positioning for floating panels.
 *
 * Generalizes the proven teleport + `position: fixed` pattern used by
 * ChatToolControls and ModelSelector: read the anchor's bounding rect, place
 * the floating element on a preferred side with a small gap, align it to the
 * anchor's start/end edge, clamp it inside the viewport, and (optionally) flip
 * to the opposite side when there isn't enough room.
 *
 * The returned `floatingStyle` is a reactive `position: fixed` style object the
 * caller binds to the floating element. Position is recomputed on open, on
 * `scroll` (capture phase, so nested scroll containers are caught) and on
 * `resize` — listeners are added/removed symmetrically from the `isOpen` watch
 * so every close path tears them down, and the scope teardown removes them too.
 */
import {
  nextTick,
  onScopeDispose,
  ref,
  watch,
  type Ref,
} from 'vue'

/** Preferred side of the anchor on which to place the floating element. */
export type FloatingPlacement = 'top' | 'bottom'

/** Horizontal alignment of the floating element relative to the anchor. */
export type FloatingAlign = 'start' | 'end'

export interface UseFloatingPositionOptions {
  /** Preferred side; default `'bottom'`. */
  placement?: FloatingPlacement
  /** Horizontal alignment to the anchor edge; default `'start'`. */
  align?: FloatingAlign
  /** Gap in px between anchor and floating element; default `8`. */
  offset?: number
  /** When true, the floating element's `min-width` matches the anchor width. */
  matchWidth?: boolean
  /** Flip to the opposite side when the preferred side lacks room; default `true`. */
  flip?: boolean
}

export interface UseFloatingPositionReturn {
  /** Reactive `position: fixed` style object to bind on the floating element. */
  floatingStyle: Ref<Record<string, string>>
  /** Force a position recompute (e.g. after the panel's content resizes). */
  update: () => void
}

/** Minimum gap (px) the floating element keeps from any viewport edge. */
const VIEWPORT_MARGIN = 8

/**
 * Compute a trigger-anchored fixed position for a floating element.
 *
 * @param anchorEl - The trigger element the panel is anchored to.
 * @param floatingEl - The floating panel element (used for size-aware flipping/clamping).
 * @param isOpen - Open-state ref; positioning + listeners are active only while true.
 * @param options - Placement, alignment, offset, matchWidth and flip behavior.
 * @returns The reactive `floatingStyle` and an imperative `update` function.
 */
export function useFloatingPosition(
  anchorEl: Ref<HTMLElement | null>,
  floatingEl: Ref<HTMLElement | null>,
  isOpen: Ref<boolean>,
  options: UseFloatingPositionOptions = {},
): UseFloatingPositionReturn {
  const {
    placement = 'bottom',
    align = 'start',
    offset = 8,
    matchWidth = false,
    flip = true,
  } = options

  const floatingStyle = ref<Record<string, string>>({})

  /** Recompute the fixed-position style from the anchor's current rect. */
  function update(): void {
    const anchor = anchorEl.value
    if (!anchor) return

    const rect = anchor.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight

    // Floating element dimensions (0 until first paint — clamps still degrade gracefully).
    const floatRect = floatingEl.value?.getBoundingClientRect()
    const floatWidth = floatRect?.width ?? rect.width
    const floatHeight = floatRect?.height ?? 0

    const style: Record<string, string> = { position: 'fixed' }

    if (matchWidth) {
      style['min-width'] = `${rect.width}px`
    }

    // ── Vertical placement (with optional flip) ──
    const spaceBelow = vh - rect.bottom
    const spaceAbove = rect.top
    let side: FloatingPlacement = placement
    if (flip) {
      const needed = floatHeight + offset + VIEWPORT_MARGIN
      if (placement === 'bottom' && spaceBelow < needed && spaceAbove > spaceBelow) {
        side = 'top'
      } else if (placement === 'top' && spaceAbove < needed && spaceBelow > spaceAbove) {
        side = 'bottom'
      }
    }

    if (side === 'bottom') {
      let top = rect.bottom + offset
      // Clamp the bottom edge inside the viewport when the height is known.
      if (floatHeight > 0 && top + floatHeight > vh - VIEWPORT_MARGIN) {
        top = Math.max(VIEWPORT_MARGIN, vh - VIEWPORT_MARGIN - floatHeight)
      }
      style['top'] = `${top}px`
    } else {
      // Anchor via `bottom` so the panel grows upward from above the trigger.
      let bottom = vh - rect.top + offset
      if (floatHeight > 0 && bottom + floatHeight > vh - VIEWPORT_MARGIN) {
        bottom = Math.max(VIEWPORT_MARGIN, vh - VIEWPORT_MARGIN - floatHeight)
      }
      style['bottom'] = `${bottom}px`
    }

    // ── Horizontal alignment + viewport clamp ──
    let left = align === 'end' ? rect.right - floatWidth : rect.left
    if (left + floatWidth > vw - VIEWPORT_MARGIN) {
      left = vw - VIEWPORT_MARGIN - floatWidth
    }
    if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN
    style['left'] = `${left}px`

    floatingStyle.value = style
  }

  function onScroll(): void {
    if (isOpen.value) update()
  }

  function onResize(): void {
    if (isOpen.value) update()
  }

  function addListeners(): void {
    // Capture phase so scrolling inside nested containers also repositions.
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
  }

  function removeListeners(): void {
    window.removeEventListener('scroll', onScroll, true)
    window.removeEventListener('resize', onResize)
  }

  watch(
    isOpen,
    (open) => {
      if (open) {
        // Compute after the floating element is in the DOM so size-aware
        // flipping/clamping has real dimensions to work with.
        nextTick(update)
        addListeners()
      } else {
        removeListeners()
      }
    },
    { immediate: true },
  )

  onScopeDispose(removeListeners)

  return { floatingStyle, update }
}
