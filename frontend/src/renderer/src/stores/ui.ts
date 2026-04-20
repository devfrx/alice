/**
 * Pinia store managing UI mode state for AL\CE.
 *
 * Supports two modes:
 * - 'assistant' — Living AI orb, voice-first interaction
 * - 'hybrid'    — Chat with ambient orb overlay
 */
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export type UIMode = 'assistant' | 'hybrid'

const LS_PLAN_CARD = 'alice_agent_plan_card_enabled'
const LS_SIDEBAR_AUTO = 'alice_agent_sidebar_auto_open'

function _loadBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return raw === '1' || raw === 'true'
  } catch {
    return fallback
  }
}

function _saveBool(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* localStorage may be unavailable */
  }
}

export const useUIStore = defineStore('ui', () => {
  const mode = ref<UIMode>(loadMode())

  /** Sidebar open state — floating sidebar starts closed. */
  const sidebarOpen = ref(false)

  // ---------------------------------------------------------------------
  // Agent UX preferences
  // ---------------------------------------------------------------------

  /** Show the inline AgentPlanCard under assistant bubbles. */
  const agentPlanCardEnabled = ref<boolean>(_loadBool(LS_PLAN_CARD, true))

  /** Auto-open the activity sidebar on the first agent.run_started event. */
  const agentSidebarAutoOpen = ref<boolean>(_loadBool(LS_SIDEBAR_AUTO, true))

  /** Runtime: whether the activity sidebar is currently visible. */
  const agentSidebarOpen = ref<boolean>(false)

  /** Run id whose plan is currently rendered inside the sidebar. */
  const agentSidebarFocusedRunId = ref<string | null>(null)

  /**
   * Per-session set of run ids the user has explicitly dismissed.
   * The sidebar will not auto-reopen for these runs even if new
   * `agent.*` events arrive.
   */
  const agentSidebarDismissedRunIds = ref<Set<string>>(new Set())

  watch(agentPlanCardEnabled, (v) => _saveBool(LS_PLAN_CARD, v))
  watch(agentSidebarAutoOpen, (v) => _saveBool(LS_SIDEBAR_AUTO, v))

  /**
   * Open the activity sidebar focusing on the given run, unless the
   * user has explicitly dismissed it for that run.
   *
   * @returns true if the sidebar was opened, false if suppressed.
   */
  function openAgentSidebar(runId: string | null): boolean {
    if (runId && agentSidebarDismissedRunIds.value.has(runId)) return false
    agentSidebarOpen.value = true
    if (runId) agentSidebarFocusedRunId.value = runId
    return true
  }

  /**
   * Close the activity sidebar and (optionally) remember the dismissal
   * for the given run so it won't auto-reopen.
   */
  function closeAgentSidebar(runId: string | null = null): void {
    agentSidebarOpen.value = false
    if (runId) agentSidebarDismissedRunIds.value.add(runId)
  }

  /** Forget all dismissals — used by tests / on logout. */
  function resetAgentSidebarDismissals(): void {
    agentSidebarDismissedRunIds.value = new Set()
  }

  /** Whether the ambient background is visible. */
  const ambientEnabled = computed(() => mode.value === 'assistant' || mode.value === 'hybrid')

  /** Whether chat panel is visible. */
  const chatVisible = computed(() => mode.value === 'hybrid')

  /** Whether the orb/living visualization is visible. */
  const orbVisible = computed(() => mode.value === 'assistant' || mode.value === 'hybrid')

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
      if (stored === 'assistant' || stored === 'hybrid') return stored
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
    chatVisible,
    orbVisible,
    setMode,
    toggleSidebar,
    // Agent UX
    agentPlanCardEnabled,
    agentSidebarAutoOpen,
    agentSidebarOpen,
    agentSidebarFocusedRunId,
    agentSidebarDismissedRunIds,
    openAgentSidebar,
    closeAgentSidebar,
    resetAgentSidebarDismissals,
  }
})
