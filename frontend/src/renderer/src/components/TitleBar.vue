<script setup lang="ts">
/**
 * TitleBar.vue — Custom frameless window title bar for O.M.N.I.A.
 *
 * Provides a draggable region with app title and native-style
 * window control buttons (minimize, maximize/restore, close).
 */
import { ref, onMounted, onUnmounted } from 'vue'

/** Tracks whether the window is currently maximized */
const isMaximized = ref(false)

const windowControls = window.electron?.windowControls

/** Minimize the application window */
const handleMinimize = (): void => {
  windowControls?.minimize()
}

/** Toggle maximize / restore */
const handleMaximize = (): void => {
  windowControls?.maximize()
  isMaximized.value = !isMaximized.value
}

/** Close the application window */
const handleClose = (): void => {
  windowControls?.close()
}

/**
 * Sync `isMaximized` when the user double-clicks the drag region
 * or the OS triggers a maximize/unmaximize via snap layouts, etc.
 */
const syncMaximizedState = (): void => {
  // matchMedia trick: maximized windows fill the screen
  isMaximized.value = window.outerWidth >= screen.availWidth && window.outerHeight >= screen.availHeight
}

onMounted(() => {
  window.addEventListener('resize', syncMaximizedState)
  syncMaximizedState()
})

onUnmounted(() => {
  window.removeEventListener('resize', syncMaximizedState)
})
</script>

<template>
  <header class="titlebar">
    <!-- Draggable region -->
    <div class="titlebar__drag-region">
      <span class="titlebar__title">O.M.N.I.A.</span>
    </div>

    <!-- Window controls (no-drag so buttons are clickable) -->
    <div class="titlebar__controls">
      <button class="titlebar__btn titlebar__btn--minimize" aria-label="Minimize" @click="handleMinimize">
        <!-- Minimize icon: horizontal line -->
        <svg width="10" height="1" viewBox="0 0 10 1">
          <rect width="10" height="1" fill="currentColor" />
        </svg>
      </button>

      <button class="titlebar__btn titlebar__btn--maximize" :aria-label="isMaximized ? 'Restore' : 'Maximize'"
        @click="handleMaximize">
        <!-- Maximize / Restore icon -->
        <svg v-if="!isMaximized" width="10" height="10" viewBox="0 0 10 10">
          <rect x="0.5" y="0.5" width="9" height="9" rx="0" fill="none" stroke="currentColor" stroke-width="1" />
        </svg>
        <svg v-else width="10" height="10" viewBox="0 0 10 10">
          <rect x="2.5" y="0.5" width="7" height="7" rx="0" fill="none" stroke="currentColor" stroke-width="1" />
          <rect x="0.5" y="2.5" width="7" height="7" rx="0" fill="var(--bg-secondary)" stroke="currentColor"
            stroke-width="1" />
        </svg>
      </button>

      <button class="titlebar__btn titlebar__btn--close" aria-label="Close" @click="handleClose">
        <!-- Close icon: X -->
        <svg width="10" height="10" viewBox="0 0 10 10">
          <line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" stroke-width="1.2" />
          <line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  display: flex;
  align-items: center;
  height: var(--titlebar-height, 34px);
  min-height: var(--titlebar-height, 34px);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  z-index: 10;
  user-select: none;
}

/* Draggable region fills all available space */
.titlebar__drag-region {
  flex: 1;
  display: flex;
  align-items: center;
  height: 100%;
  padding-left: 12px;
  -webkit-app-region: drag;
}

.titlebar__title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--text-muted);
}

/* Control button group */
.titlebar__controls {
  display: flex;
  height: 100%;
  -webkit-app-region: no-drag;
}

.titlebar__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.titlebar__btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.titlebar__btn:active {
  background: rgba(255, 255, 255, 0.04);
}

.titlebar__btn--close:hover {
  background: var(--danger);
  color: #ffffff;
}

.titlebar__btn--close:active {
  background: rgba(180, 60, 60, 0.9);
  color: #ffffff;
}
</style>
