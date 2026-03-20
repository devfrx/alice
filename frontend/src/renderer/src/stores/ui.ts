/**
 * Pinia store managing UI mode state for OMNIA.
 *
 * Supports two modes:
 * - 'assistant' — Living AI orb, voice-first interaction
 * - 'hybrid'    — Chat with ambient orb overlay
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type UIMode = 'assistant' | 'hybrid'

export const useUIStore = defineStore('ui', () => {
  const mode = ref<UIMode>(loadMode())

  /** Sidebar open state — floating sidebar starts closed. */
  const sidebarOpen = ref(false)

  /** Whether the ambient background is visible. */
  const ambientEnabled = computed(() => mode.value === 'assistant' || mode.value === 'hybrid')

  /** Whether chat panel is visible. */
  const chatVisible = computed(() => mode.value === 'hybrid')

  /** Whether the orb/living visualization is visible. */
  const orbVisible = computed(() => mode.value === 'assistant' || mode.value === 'hybrid')

  function setMode(newMode: UIMode): void {
    mode.value = newMode
    try {
      localStorage.setItem('omnia_ui_mode', newMode)
    } catch {
      /* localStorage may be unavailable */
    }
  }

  function loadMode(): UIMode {
    try {
      const stored = localStorage.getItem('omnia_ui_mode')
      if (stored === 'assistant' || stored === 'hybrid') return stored
    } catch {
      /* localStorage may be unavailable */
    }
    return 'assistant'
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  return { mode, sidebarOpen, ambientEnabled, chatVisible, orbVisible, setMode, toggleSidebar }
})
