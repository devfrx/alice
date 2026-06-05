/**
 * Pinia store managing the workspace tiling layout and sidebar state for AL\CE.
 *
 * Wraps the pure tiling-tree functions from composables/workspace/tilingTree.ts
 * as the single source of mutation, with localStorage persistence and version-
 * guarded migration.
 */
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
  createEmptyLayout,
  openModule as treeOpenModule,
  closeLeaf as treeCloseLeaf,
  setRatio as treeSetRatio,
  findLeaf
} from '../composables/workspace/tilingTree'
import type { WorkspaceLayout, LeafNode, TileNode } from '../composables/workspace/tilingTypes'

// ---------------------------------------------------------------------------
// Persistence key constants
// ---------------------------------------------------------------------------

export const LAYOUT_KEY = 'alice_workspace_layout_v1'
const SIDEBAR_KEY = 'alice_workspace_sidebar'
const AUTOOPEN_KEY = 'alice_workspace_autoopen'

// ---------------------------------------------------------------------------
// Sidebar mode type
// ---------------------------------------------------------------------------

export type SidebarMode = 'expanded' | 'rail' | 'closed'

// ---------------------------------------------------------------------------
// Migration helpers
// ---------------------------------------------------------------------------

function _isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function _validateNode(node: unknown, isModuleRegistered: (id: string) => boolean): boolean {
  if (!_isObject(node)) return false
  if (node.kind === 'leaf') {
    if (typeof node.id !== 'string' || node.id === '') return false
    if (typeof node.moduleId !== 'string' || node.moduleId === '') return false
    if (!isModuleRegistered(node.moduleId)) return false
    if (node.params !== undefined && !_isObject(node.params)) return false
    return true
  }
  if (node.kind === 'split') {
    if (typeof node.id !== 'string' || node.id === '') return false
    if (node.orientation !== 'horizontal' && node.orientation !== 'vertical') return false
    if (typeof node.ratio !== 'number') return false
    if (!Array.isArray(node.children) || node.children.length !== 2) return false
    return (
      _validateNode(node.children[0], isModuleRegistered) &&
      _validateNode(node.children[1], isModuleRegistered)
    )
  }
  return false
}

/**
 * Validate and migrate a raw persisted value into a WorkspaceLayout.
 *
 * Rules:
 * - If raw is not an object, version !== 1, or structure is malformed → empty layout.
 * - If ANY leaf has an unregistered moduleId → drop the whole layout (safe, no partial tree).
 * - Ensures activeLeafId references an existing leaf; otherwise resets it to null.
 *
 * @param raw               The JSON.parsed value from localStorage.
 * @param isModuleRegistered Predicate injected so this fn has no registry dep. Defaults to () => true.
 */
export function migrateLayout(
  raw: unknown,
  isModuleRegistered: (id: string) => boolean = () => true
): WorkspaceLayout {
  if (!_isObject(raw)) return createEmptyLayout()
  if (raw.version !== 1) return createEmptyLayout()

  // root must be null or a valid node tree
  if (raw.root !== null) {
    if (!_validateNode(raw.root, isModuleRegistered)) return createEmptyLayout()
  }

  const root = (raw.root ?? null) as TileNode | null

  // Validate activeLeafId
  let activeLeafId: string | null = null
  if (typeof raw.activeLeafId === 'string' && root !== null) {
    const leaf = findLeaf(root, raw.activeLeafId)
    activeLeafId = leaf !== null ? leaf.id : null
  }

  return { version: 1, root, activeLeafId }
}

// ---------------------------------------------------------------------------
// Persistence read helpers
// ---------------------------------------------------------------------------

function loadLayout(): WorkspaceLayout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (raw === null) return createEmptyLayout()
    return migrateLayout(JSON.parse(raw) as unknown)
  } catch {
    return createEmptyLayout()
  }
}

function _loadSidebarMode(): SidebarMode {
  try {
    const raw = localStorage.getItem(SIDEBAR_KEY)
    if (raw === 'expanded' || raw === 'rail' || raw === 'closed') return raw
  } catch {
    /* localStorage may be unavailable */
  }
  return 'expanded'
}

function _loadSidebarWidth(): number {
  try {
    const raw = localStorage.getItem(`${SIDEBAR_KEY}_width`)
    if (raw !== null) {
      const n = parseInt(raw, 10)
      if (!isNaN(n)) return Math.min(420, Math.max(180, n))
    }
  } catch {
    /* localStorage may be unavailable */
  }
  return 260
}

function _loadAutoOpen(): boolean {
  try {
    const raw = localStorage.getItem(AUTOOPEN_KEY)
    if (raw === null) return true
    return raw === '1' || raw === 'true'
  } catch {
    return true
  }
}

// ---------------------------------------------------------------------------
// Persistence write helpers
// ---------------------------------------------------------------------------

function _saveStr(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* localStorage may be unavailable */
  }
}

function _saveBool(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* localStorage may be unavailable */
  }
}

// ---------------------------------------------------------------------------
// Store definition
// ---------------------------------------------------------------------------

export const useWorkspaceStore = defineStore('workspace', () => {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  const layout = ref<WorkspaceLayout>(loadLayout())
  const sidebarMode = ref<SidebarMode>(_loadSidebarMode())
  const sidebarWidth = ref<number>(_loadSidebarWidth())
  const autoOpenEnabled = ref<boolean>(_loadAutoOpen())

  /** Transient — NOT persisted. True while a panel divider drag is in progress. */
  const isResizing = ref<boolean>(false)

  // -------------------------------------------------------------------------
  // Computed
  // -------------------------------------------------------------------------

  /** True when at least one module tile is open. */
  const hasModules = computed<boolean>(() => layout.value.root !== null)

  /** The currently active LeafNode, or null if none. */
  const activeLeaf = computed<LeafNode | null>(() => {
    const { root, activeLeafId } = layout.value
    if (root === null || activeLeafId === null) return null
    return findLeaf(root, activeLeafId)
  })

  // -------------------------------------------------------------------------
  // Layout actions (wrap pure tree fns; persist inside each action)
  // -------------------------------------------------------------------------

  function _persistLayout(): void {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout.value))
    } catch {
      /* localStorage may be unavailable */
    }
  }

  function openModule(moduleId: string, params?: Record<string, unknown>): void {
    layout.value = treeOpenModule(layout.value, moduleId, params)
    _persistLayout()
  }

  function closeLeaf(leafId: string): void {
    layout.value = treeCloseLeaf(layout.value, leafId)
    _persistLayout()
  }

  function setRatio(splitId: string, ratio: number): void {
    layout.value = treeSetRatio(layout.value, splitId, ratio)
    _persistLayout()
  }

  function resetLayout(): void {
    layout.value = createEmptyLayout()
    _persistLayout()
  }

  // -------------------------------------------------------------------------
  // Sidebar actions
  // -------------------------------------------------------------------------

  function setSidebarMode(m: SidebarMode): void {
    sidebarMode.value = m
    _saveStr(SIDEBAR_KEY, m)
  }

  function setSidebarWidth(n: number): void {
    sidebarWidth.value = Math.min(420, Math.max(180, n))
    _saveStr(`${SIDEBAR_KEY}_width`, String(sidebarWidth.value))
  }

  // -------------------------------------------------------------------------
  // Auto-open actions
  // -------------------------------------------------------------------------

  function toggleAutoOpen(): void {
    autoOpenEnabled.value = !autoOpenEnabled.value
    _saveBool(AUTOOPEN_KEY, autoOpenEnabled.value)
  }

  function setAutoOpen(v: boolean): void {
    autoOpenEnabled.value = v
    _saveBool(AUTOOPEN_KEY, v)
  }

  // -------------------------------------------------------------------------
  // Transient actions
  // -------------------------------------------------------------------------

  function setResizing(v: boolean): void {
    isResizing.value = v
  }

  // -------------------------------------------------------------------------
  // Watcher: also persist layout on deep reactive changes (covers any
  // external direct assignment to layout.value not via actions).
  // -------------------------------------------------------------------------
  watch(layout, _persistLayout, { deep: true })

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  return {
    // State
    layout,
    sidebarMode,
    sidebarWidth,
    autoOpenEnabled,
    isResizing,
    // Computed
    hasModules,
    activeLeaf,
    // Layout actions
    openModule,
    closeLeaf,
    setRatio,
    resetLayout,
    // Sidebar actions
    setSidebarMode,
    setSidebarWidth,
    // Auto-open actions
    toggleAutoOpen,
    setAutoOpen,
    // Transient actions
    setResizing
  }
})
