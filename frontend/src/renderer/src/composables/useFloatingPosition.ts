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
import { nextTick, onScopeDispose, ref, watch, type Ref } from 'vue'

/** Preferred side of the anchor on which to place the floating element. */
export type FloatingPlacement = 'top' | 'bottom'

/** Horizontal alignment of the floating element relative to the anchor. */
export type FloatingAlign = 'start' | 'center' | 'end'

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
  options: UseFloatingPositionOptions = {}
): UseFloatingPositionReturn {
  const {
    placement = 'bottom',
    align = 'start',
    offset = 8,
    matchWidth = false,
    flip = true
  } = options

  // Start hidden + fixed (never `static`) so the panel can't flash at the
  // document-flow top-left before the first measurement lands.
  const HIDDEN_STYLE: Record<string, string> = {
    position: 'fixed',
    top: '-9999px',
    left: '-9999px',
    visibility: 'hidden'
  }
  const floatingStyle = ref<Record<string, string>>({ ...HIDDEN_STYLE })

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
    let left: number
    if (align === 'center') left = rect.left + rect.width / 2 - floatWidth / 2
    else if (align === 'end') left = rect.right - floatWidth
    else left = rect.left
    if (left + floatWidth > vw - VIEWPORT_MARGIN) {
      left = vw - VIEWPORT_MARGIN - floatWidth
    }
    if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN
    style['left'] = `${left}px`

    // Reveal only once the panel has a real measured size, so we never paint
    // it at a stale/zero-size position. Until then it stays hidden (off-screen).
    style['visibility'] = floatRect && floatRect.width > 0 ? 'visible' : 'hidden'

    floatingStyle.value = style
  }

  function onScroll(): void {
    if (isOpen.value) update()
  }

  function onResize(): void {
    if (isOpen.value) update()
  }

  /**
   * Observes both anchor and floating element so the panel repositions when
   * either changes size — crucially, when the floating element gains its real
   * size after first paint (the source of the "wrong position on first open"
   * bug, where the panel measured 0×0 before content laid out).
   */
  let resizeObserver: ResizeObserver | null = null

  function addListeners(): void {
    // Capture phase so scrolling inside nested containers also repositions.
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        if (isOpen.value) update()
      })
      // The floating element only exists after the next DOM flush; observe both
      // once it is mounted.
      nextTick(() => {
        if (!resizeObserver) return
        if (floatingEl.value) resizeObserver.observe(floatingEl.value)
        if (anchorEl.value) resizeObserver.observe(anchorEl.value)
      })
    }
  }

  function removeListeners(): void {
    window.removeEventListener('scroll', onScroll, true)
    window.removeEventListener('resize', onResize)
    resizeObserver?.disconnect()
    resizeObserver = null
  }

  watch(
    isOpen,
    (open) => {
      if (open) {
        // Hide first so the panel never flashes at a stale/zero position, then
        // measure on the next DOM flush and again after paint settles (covers
        // layout that shifts post-navigation or while sidebar/panels animate).
        floatingStyle.value = { ...HIDDEN_STYLE }
        addListeners()
        nextTick(update)
        requestAnimationFrame(() => {
          if (isOpen.value) update()
        })
      } else {
        removeListeners()
      }
    },
    { immediate: true }
  )

  onScopeDispose(removeListeners)

  return { floatingStyle, update }
}
