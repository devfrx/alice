<script setup lang="ts">
/**
 * DockedSidebar — inline, resizable, collapsible frame on the left of the
 * shell that hosts {@link AppSidebar} in its docked variant.
 *
 * ── Visibility (single source of truth) ───────────────────────────────────
 * `uiStore.sidebarOpen` (boolean) is the ONLY driver of OPEN ↔ CLOSED. It is
 * wired to the EXISTING TitleBar toggle button. When false the frame collapses
 * to zero width; reopening is done exclusively via the TitleBar toggle (there
 * is no in-frame floating reopen affordance). Closing is done via the X button
 * in the sidebar header (which flips this same flag).
 *
 * `sidebarWidth` controls how wide the frame is WHEN visible. There is no
 * intermediate "rail"/reduce mode — the sidebar is either expanded or closed.
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

/** Visible when the UI store says open. */
const isVisible = computed(() => uiStore.sidebarOpen)

/** Effective frame width in px (0 when collapsed). */
const frameWidth = computed<number>(() => (isVisible.value ? size.value : 0))

/** Collapse the whole frame (TitleBar toggle reopens). */
function collapse(): void {
  uiStore.sidebarOpen = false
}
</script>

<template>
  <!-- Frame in normal flow; width animates between 0 (closed) and expanded. -->
  <div
    class="docked-sidebar"
    :class="{
      'docked-sidebar--collapsed': !isVisible,
      'docked-sidebar--dragging': isDragging
    }"
    :style="{ width: frameWidth + 'px' }"
  >
    <!-- Full sidebar body. Closing is via the X in the sidebar header. -->
    <div v-if="isVisible" class="docked-sidebar__body">
      <div class="docked-sidebar__controls">
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
</template>

<style scoped>
.docked-sidebar {
  position: relative;
  flex-shrink: 0;
  height: calc(100% - 2 * var(--gutter-lg, 10px));
  margin: var(--gutter-lg, 10px) 0 var(--gutter-lg, 10px) var(--gutter-lg, 10px);
  overflow: hidden;
  /* Solid, fully-opaque surface — no glass / semi-transparency. */
  background: var(--surface-1);
  /* Subtle hairline + soft shadow for light separation (not a heavy frame). */
  border: 1px solid var(--border);
  border-radius: var(--panel-radius, var(--radius-lg));
  box-shadow: var(--panel-shadow, var(--shadow-md));
  transition: width var(--transition-fast, 160ms) var(--ease-out, ease);
  /* Sits in normal flow — modals/toasts (teleported) render above. */
  z-index: auto;
}

/* Collapsed: no card chrome and no gutter so the workspace reclaims the space. */
.docked-sidebar--collapsed {
  margin: 0;
  height: 100%;
  border: none;
  border-radius: 0;
  box-shadow: none;
}

.docked-sidebar--dragging {
  transition: none;
  user-select: none;
}

/* ── Controls (close button) ───────────────────────────────────────── */
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
  right: calc(var(--space-3, 12px) + 6px);
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

@media (prefers-reduced-motion: reduce) {
  .docked-sidebar {
    transition: none;
  }
}
</style>
