/**
 * Pinia store for shell UI state.
 *
 * Since Fase 6 the route is the single source of truth for which surface is
 * on screen (Horizon is the only chat surface); this store only tracks shell
 * chrome: the docked sidebar's open state and persisted width.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

const SIDEBAR_WIDTH_KEY = 'alice_sidebar_width'

function loadSidebarWidth(): number {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY)
    if (raw !== null) {
      const n = parseInt(raw, 10)
      if (!isNaN(n)) return Math.min(420, Math.max(200, n))
    }
  } catch {
    /* localStorage may be unavailable */
  }
  return 260
}

export const useUIStore = defineStore('ui', () => {
  /**
   * Sidebar open state — source of truth for the docked sidebar's
   * expanded ↔ closed state (wired to the TitleBar toggle).
   */
  const sidebarOpen = ref(true)

  /** Persisted sidebar width in px (clamped 200–420). */
  const sidebarWidth = ref<number>(loadSidebarWidth())

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  function setSidebarWidth(n: number): void {
    sidebarWidth.value = Math.min(420, Math.max(200, n))
    try {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth.value))
    } catch {
      /* localStorage may be unavailable */
    }
  }

  return {
    sidebarOpen,
    sidebarWidth,
    toggleSidebar,
    setSidebarWidth
  }
})
