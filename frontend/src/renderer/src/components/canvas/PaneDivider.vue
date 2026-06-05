<script setup lang="ts">
/**
 * PaneDivider — Draggable seam between two tiles in a SplitContainer.
 *
 * Converts a pointer drag into a parent-relative RATIO (the first child's
 * main-axis fraction) and emits it. The conversion is `deltaPx /
 * containerSize`, where `containerSize` is the parent's px extent along the
 * split's main axis (supplied by SplitContainer).
 *
 * A small focused pointer handler is used here rather than useResizablePane:
 * that composable is px-based and clamps to px bounds, whereas this divider
 * must clamp a RATIO against a live container size. A dedicated handler keeps
 * the math obvious and avoids leaks via onBeforeUnmount cleanup.
 */
import { onBeforeUnmount } from 'vue'
import { useWorkspaceStore } from '../../stores/workspace'
import type { SplitOrientation } from '../../composables/workspace/tilingTypes'

const props = defineProps<{
  /** Split orientation that owns this divider. */
  orientation: SplitOrientation
  /** Current first-child ratio, clamped [0.1, 0.9]. */
  ratio: number
  /** Parent px extent along the split's main axis. */
  containerSize: number
}>()

const emit = defineEmits<{
  'update:ratio': [ratio: number]
  'resize-start': []
  'resize-end': []
}>()

const workspaceStore = useWorkspaceStore()

const RATIO_MIN = 0.1
const RATIO_MAX = 0.9

function clampRatio(v: number): number {
  return Math.min(RATIO_MAX, Math.max(RATIO_MIN, v))
}

// 'horizontal' split → children side-by-side, drag along X.
// 'vertical' split   → children stacked, drag along Y.
const isHorizontal = (): boolean => props.orientation === 'horizontal'

let startCoord = 0
let startRatio = 0
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

  startCoord = isHorizontal() ? e.clientX : e.clientY
  startRatio = props.ratio

  workspaceStore.setResizing(true)
  emit('resize-start')

  // Safety guard against any leaked listeners.
  cleanup()

  onMove = (ev: MouseEvent): void => {
    if (props.containerSize <= 0) return
    const currentCoord = isHorizontal() ? ev.clientX : ev.clientY
    const deltaPx = currentCoord - startCoord
    const newRatio = clampRatio(startRatio + deltaPx / props.containerSize)
    emit('update:ratio', newRatio)
  }

  onUp = (): void => {
    workspaceStore.setResizing(false)
    emit('resize-end')
    cleanup()
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

onBeforeUnmount(() => {
  // Ensure the global resizing flag does not get stuck if we unmount mid-drag.
  if (onMove || onUp) {
    workspaceStore.setResizing(false)
  }
  cleanup()
})
</script>

<template>
  <div
    class="pane-divider"
    :class="orientation === 'horizontal' ? 'pane-divider--x' : 'pane-divider--y'"
    role="separator"
    :aria-orientation="orientation === 'horizontal' ? 'vertical' : 'horizontal'"
    @mousedown="onMouseDown"
  >
    <span class="pane-divider__grip" aria-hidden="true" />
  </div>
</template>

<style scoped>
.pane-divider {
  position: relative;
  flex: 0 0 6px;
  align-self: stretch;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-raised, 2);
  background: transparent;
  transition: background-color var(--duration-fast, 120ms) ease;
}

.pane-divider--x {
  cursor: col-resize;
  width: 6px;
}

.pane-divider--y {
  cursor: row-resize;
  height: 6px;
}

.pane-divider:hover,
.pane-divider:active {
  background: var(--accent-dim, rgba(255, 255, 255, 0.04));
}

.pane-divider__grip {
  background: var(--border, rgba(255, 255, 255, 0.12));
  border-radius: var(--radius-full, 9999px);
  transition:
    background-color var(--duration-fast, 120ms) ease,
    opacity var(--duration-fast, 120ms) ease;
  opacity: 0.6;
}

.pane-divider--x .pane-divider__grip {
  width: 2px;
  height: 28px;
}

.pane-divider--y .pane-divider__grip {
  width: 28px;
  height: 2px;
}

.pane-divider:hover .pane-divider__grip {
  background: var(--accent, var(--text-secondary));
  opacity: 1;
}
</style>
