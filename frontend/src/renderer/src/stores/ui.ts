/**
 * Pinia store for shell UI state.
 *
 * Tracks:
 * - `mode` — which of the two primary chat surfaces is active ('assistant'
 *   Horizon scene, 'workspace' tiling panels). The router's `afterEach`
 *   keeps it in sync with the active route; secondary routes (settings,
 *   email, …) do not touch it, so "return to chat surface" navigation stays
 *   coherent.
 * - Docked sidebar chrome: open state and persisted width.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type UIMode = 'assistant' | 'workspace'

const MODE_KEY = 'alice_ui_mode'
const SIDEBAR_WIDTH_KEY = 'alice_sidebar_width'

function loadMode(): UIMode {
  try {
    const stored = localStorage.getItem(MODE_KEY)
    if (stored === 'assistant' || stored === 'workspace') return stored
  } catch {
    /* localStorage may be unavailable */
  }
  return 'workspace'
}

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
  /** Active primary chat surface (route-synced via router afterEach). */
  const mode = ref<UIMode>(loadMode())

  /**
   * Sidebar open state — source of truth for the docked sidebar's
   * expanded ↔ closed state (wired to the TitleBar toggle).
   */
  const sidebarOpen = ref(true)

  /** Persisted sidebar width in px (clamped 200–420). */
  const sidebarWidth = ref<number>(loadSidebarWidth())

  function setMode(newMode: UIMode): void {
    mode.value = newMode
    try {
      localStorage.setItem(MODE_KEY, newMode)
    } catch {
      /* localStorage may be unavailable */
    }
  }

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
    mode,
    sidebarOpen,
    sidebarWidth,
    setMode,
    toggleSidebar,
    setSidebarWidth
  }
})
