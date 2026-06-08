/**
 * Pinia store managing UI mode state for AL\CE.
 *
 * Active modes (the two primary chat surfaces):
 * - 'assistant' — Living AI orb, voice-first interaction.
 * - 'workspace' — Tiling panel workspace.
 *
 * `mode` tracks whichever primary surface is active so the shell (root body
 * class, ambient/orb gating, "return to chat surface" navigation) stays
 * coherent. The router's `afterEach` keeps it in sync with the active route.
 *
 * The 'hybrid' dual-pane mode was retired (R3) in favour of Workspace; the
 * `/hybrid → /workspace` router redirect preserves old deep links, and any
 * stale persisted `alice_ui_mode = 'hybrid'` resolves to 'assistant' on load.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type UIMode = 'assistant' | 'workspace'

export const useUIStore = defineStore('ui', () => {
  const mode = ref<UIMode>(loadMode())

  /**
   * Sidebar open state — source of truth for the docked sidebar's
   * visible(expanded/rail) ↔ closed state. Starts open since the docked
   * sidebar is now a primary surface of the shell.
   */
  const sidebarOpen = ref(true)

  /** Whether the ambient background is visible. */
  const ambientEnabled = computed(() => mode.value === 'assistant')

  /** Whether the orb/living visualization is visible. */
  const orbVisible = computed(() => mode.value === 'assistant')

  function setMode(newMode: UIMode): void {
    mode.value = newMode
    try {
      localStorage.setItem('alice_ui_mode', newMode)
    } catch {
      /* localStorage may be unavailable */
    }
  }

  function loadMode(): UIMode {
    try {
      const stored = localStorage.getItem('alice_ui_mode')
      if (stored === 'assistant' || stored === 'workspace') return stored
      // Legacy 'hybrid' (retired R3) and any other value fall through to 'assistant'.
    } catch {
      /* localStorage may be unavailable */
    }
    return 'assistant'
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  return {
    mode,
    sidebarOpen,
    ambientEnabled,
    orbVisible,
    setMode,
    toggleSidebar,
  }
})
