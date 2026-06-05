<script setup lang="ts">
/**
 * DockedSidebar — inline, resizable, collapsible frame on the left of the
 * shell that hosts {@link AppSidebar} in its docked variant.
 *
 * ── Toggle mapping (single source of truth, no double-toggle) ──────────────
 * Two independent concerns drive this frame:
 *
 *   1. `uiStore.sidebarOpen` (boolean) — VISIBLE ↔ CLOSED. This is the source
 *      of truth wired to the EXISTING TitleBar toggle button. When false the
 *      frame collapses to zero width and only a small floating reopen
 *      affordance remains. The TitleBar button (and the in-frame collapse
 *      button) flip exactly this flag — nothing else.
 *
 *   2. `workspaceStore.sidebarMode` ('expanded' | 'rail' | 'closed') +
 *      `sidebarWidth` — control HOW the frame looks WHEN visible. We only ever
 *      toggle between 'expanded' (full sidebar) and 'rail' (narrow strip with
 *      an expand button) here; the 'closed' value is treated as collapsed too
 *      but is never written by this component (we use `sidebarOpen` for that).
 *
 * Because visibility lives solely in `sidebarOpen` and width/rail lives solely
 * in `sidebarMode`, the two never fight: the TitleBar toggle shows/hides, the
 * in-frame rail button changes width presentation, and there is exactly one
 * writer per piece of state.
 *
 * The frame sits in normal document flow (z-index: auto) so teleported
 * modals/toasts (z-modal / z-toast) always render above it.
 */
import { computed, watch } from 'vue'
import AppSidebar from '../sidebar/AppSidebar.vue'
import AppIcon from '../ui/AppIcon.vue'
import { useResizablePane } from '../../composables/useResizablePane'
import { useUIStore } from '../../stores/ui'
import { useWorkspaceStore } from '../../stores/workspace'

const RAIL_WIDTH = 48

const uiStore = useUIStore()
const workspaceStore = useWorkspaceStore()

// Resizable width, initialised from the persisted store value. We keep the
// composable's `size` in sync with the store and commit back on every change
// so the width persists across sessions.
const { size, isDragging, onMouseDown, setSize } = useResizablePane({
  axis: 'x',
  min: 200,
  max: 420,
  initial: workspaceStore.sidebarWidth
})

// Commit resize → store (persists).
watch(size, (v) => {
  if (v !== workspaceStore.sidebarWidth) workspaceStore.setSidebarWidth(v)
})

// If the store width changes elsewhere, mirror it into the composable.
watch(
  () => workspaceStore.sidebarWidth,
  (v) => {
    if (v !== size.value) setSize(v)
  }
)

/** Visible when the UI store says open AND not explicitly railed/closed mode. */
const isVisible = computed(() => uiStore.sidebarOpen)

/** Rail (narrow) presentation when visible but mode === 'rail'. */
const isRail = computed(() => isVisible.value && workspaceStore.sidebarMode === 'rail')

/** Full sidebar shown only when visible and not in rail mode. */
const showFull = computed(() => isVisible.value && !isRail.value)

/** Effective frame width in px. */
const frameWidth = computed<number>(() => {
  if (!isVisible.value) return 0
  if (isRail.value) return RAIL_WIDTH
  return size.value
})

/** Collapse the whole frame (TitleBar toggle mirrors this). */
function collapse(): void {
  uiStore.sidebarOpen = false
}

/** Reopen the frame to its last expanded/rail state. */
function reopen(): void {
  uiStore.sidebarOpen = true
}

/** Switch between full (expanded) and rail presentations while visible. */
function toRail(): void {
  workspaceStore.setSidebarMode('rail')
}

function toExpanded(): void {
  workspaceStore.setSidebarMode('expanded')
}
</script>

<template>
  <!-- Frame in normal flow; width animates between 0 / rail / expanded. -->
  <div
    class="docked-sidebar"
    :class="{
      'docked-sidebar--collapsed': !isVisible,
      'docked-sidebar--rail': isRail,
      'docked-sidebar--dragging': isDragging
    }"
    :style="{ width: frameWidth + 'px' }"
  >
    <!-- Rail: narrow strip with an expand affordance. -->
    <div v-if="isRail" class="docked-sidebar__rail">
      <button
        type="button"
        class="docked-sidebar__rail-btn"
        aria-label="Espandi sidebar"
        title="Espandi"
        @click="toExpanded"
      >
        <AppIcon name="hybrid-sidebar" :size="16" />
      </button>
      <button
        type="button"
        class="docked-sidebar__rail-btn"
        aria-label="Chiudi sidebar"
        title="Chiudi"
        @click="collapse"
      >
        <AppIcon name="x" :size="14" :stroke-width="2.5" />
      </button>
    </div>

    <!-- Full sidebar body. -->
    <div v-else-if="showFull" class="docked-sidebar__body">
      <div class="docked-sidebar__controls">
        <button
          type="button"
          class="docked-sidebar__ctrl-btn"
          aria-label="Comprimi in barra"
          title="Comprimi"
          @click="toRail"
        >
          <AppIcon name="hybrid-sidebar" :size="14" />
        </button>
        <button
          type="button"
          class="docked-sidebar__ctrl-btn"
          aria-label="Chiudi sidebar"
          title="Chiudi"
          @click="collapse"
        >
          <AppIcon name="x" :size="14" :stroke-width="2.5" />
        </button>
      </div>

      <AppSidebar docked />

      <!-- Resize divider on the right edge. -->
      <div
        class="docked-sidebar__divider"
        :class="{ 'docked-sidebar__divider--active': isDragging }"
        @mousedown="onMouseDown"
      />
    </div>
  </div>

  <!-- Floating reopen affordance when fully collapsed. -->
  <button
    v-if="!isVisible"
    type="button"
    class="docked-sidebar__reopen"
    aria-label="Apri sidebar"
    title="Apri sidebar"
    @click="reopen"
  >
    <AppIcon name="hybrid-sidebar" :size="16" />
  </button>
</template>

<style scoped>
.docked-sidebar {
  position: relative;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  transition: width var(--transition-fast, 160ms) var(--ease-out, ease);
  /* Sits in normal flow — modals/toasts (teleported) render above. */
  z-index: auto;
}

.docked-sidebar--collapsed {
  border-right: none;
}

.docked-sidebar--dragging {
  transition: none;
  user-select: none;
}

/* ── Rail ──────────────────────────────────────────────────────────── */
.docked-sidebar__rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1, 4px);
  padding: var(--space-2, 8px) 0;
  height: 100%;
}

.docked-sidebar__rail-btn,
.docked-sidebar__ctrl-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.docked-sidebar__rail-btn:hover,
.docked-sidebar__ctrl-btn:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
  border-color: var(--border);
}

/* ── Full body ─────────────────────────────────────────────────────── */
.docked-sidebar__body {
  position: relative;
  width: 100%;
  height: 100%;
}

.docked-sidebar__controls {
  position: absolute;
  top: var(--space-2, 8px);
  right: var(--space-3, 12px);
  z-index: 2;
  display: flex;
  gap: var(--space-0-5, 2px);
}

/* ── Resize divider ────────────────────────────────────────────────── */
.docked-sidebar__divider {
  position: absolute;
  top: 0;
  right: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  background: transparent;
  transition: background var(--transition-fast);
  z-index: 3;
}

.docked-sidebar__divider:hover,
.docked-sidebar__divider--active {
  background: var(--accent-border);
}

/* ── Floating reopen affordance ────────────────────────────────────── */
.docked-sidebar__reopen {
  position: absolute;
  top: calc(var(--titlebar-height, 38px) + var(--space-2, 8px));
  left: var(--space-2, 8px);
  z-index: var(--z-sticky, 100);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition:
    color var(--transition-fast),
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.docked-sidebar__reopen:hover {
  color: var(--text-primary);
  background: var(--surface-3);
  border-color: var(--border-hover);
}

@media (prefers-reduced-motion: reduce) {
  .docked-sidebar {
    transition: none;
  }
}
</style>
