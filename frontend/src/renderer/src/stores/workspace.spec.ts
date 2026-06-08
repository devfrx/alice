/**
 * Unit tests for stores/workspace.ts
 *
 * Environment: vitest node (no jsdom).
 * Pinia is instantiated fresh per test; localStorage is stubbed with an
 * in-memory Map-backed shim so no real browser storage is needed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkspaceStore, migrateLayout, LAYOUT_KEY } from './workspace'
import {
  createEmptyLayout,
  openModule as treeOpenModule
} from '../composables/workspace/tilingTree'
import type { LeafNode, SplitNode } from '../composables/workspace/tilingTypes'

// ---------------------------------------------------------------------------
// In-memory localStorage shim
// ---------------------------------------------------------------------------

function makeLocalStorageShim(): {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
  clear: () => void
  _store: Map<string, string>
} {
  const store = new Map<string, string>()
  return {
    getItem: (key: string): string | null => store.get(key) ?? null,
    setItem: (key: string, value: string): void => {
      store.set(key, value)
    },
    removeItem: (key: string): void => {
      store.delete(key)
    },
    clear: (): void => {
      store.clear()
    },
    _store: store
  }
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('localStorage', makeLocalStorageShim())
})

// ---------------------------------------------------------------------------
// 1. Fresh store defaults
// ---------------------------------------------------------------------------

describe('fresh store', () => {
  it('starts with an empty layout', () => {
    const ws = useWorkspaceStore()
    expect(ws.layout).toEqual(createEmptyLayout())
    expect(ws.hasModules).toBe(false)
    expect(ws.activeLeaf).toBeNull()
  })

  it('has correct default sidebar/autoOpen state', () => {
    const ws = useWorkspaceStore()
    expect(ws.sidebarMode).toBe('expanded')
    expect(ws.sidebarWidth).toBe(260)
    expect(ws.autoOpenEnabled).toBe(true)
    expect(ws.isResizing).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 2. openModule / activeLeaf / tree structure
// ---------------------------------------------------------------------------

describe('openModule', () => {
  it('openModule sets hasModules true and activeLeaf to the opened module', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    expect(ws.hasModules).toBe(true)
    expect(ws.activeLeaf).not.toBeNull()
    expect((ws.activeLeaf as LeafNode).moduleId).toBe('chart')
  })

  it('two opens → hasModules true, activeLeaf is second module, root is a split', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.openModule('cad3d')

    expect(ws.hasModules).toBe(true)
    expect(ws.activeLeaf).not.toBeNull()
    expect((ws.activeLeaf as LeafNode).moduleId).toBe('cad3d')

    const root = ws.layout.root as SplitNode
    expect(root.kind).toBe('split')
    expect(root.children.length).toBe(2)
    expect((root.children[0] as LeafNode).moduleId).toBe('chart')
    expect((root.children[1] as LeafNode).moduleId).toBe('cad3d')
  })
})

// ---------------------------------------------------------------------------
// 2b. Single-instance + toggle (Fase 7 D)
// ---------------------------------------------------------------------------

describe('single-instance + toggle', () => {
  it('re-opening the same module focuses the existing tile (no duplicate)', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    const firstId = (ws.activeLeaf as LeafNode).id
    ws.openModule('cad3d') // focus moves to cad3d
    ws.openModule('chart') // re-open chart → should focus, not duplicate
    expect((ws.activeLeaf as LeafNode).moduleId).toBe('chart')
    expect((ws.activeLeaf as LeafNode).id).toBe(firstId)
    // Only two tiles total (chart + cad3d), root remains a single split.
    const root = ws.layout.root as SplitNode
    expect(root.kind).toBe('split')
    expect(root.children.every((c) => c.kind === 'leaf')).toBe(true)
  })

  it('toggleModule opens when absent and closes when present', () => {
    const ws = useWorkspaceStore()
    expect(ws.isModuleOpen('chart')).toBe(false)
    ws.toggleModule('chart')
    expect(ws.isModuleOpen('chart')).toBe(true)
    ws.toggleModule('chart')
    expect(ws.isModuleOpen('chart')).toBe(false)
    expect(ws.hasModules).toBe(false)
  })

  it('openModuleIds and activeModuleId reflect the live layout', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.openModule('cad3d')
    expect(ws.openModuleIds.has('chart')).toBe(true)
    expect(ws.openModuleIds.has('cad3d')).toBe(true)
    expect(ws.openModuleIds.has('plan')).toBe(false)
    expect(ws.activeModuleId).toBe('cad3d')
  })
})

// ---------------------------------------------------------------------------
// 3. closeLeaf
// ---------------------------------------------------------------------------

describe('closeLeaf', () => {
  it('closing the active leaf reduces the tree', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.openModule('cad3d')

    const leafId = (ws.activeLeaf as LeafNode).id
    ws.closeLeaf(leafId)

    // One module should remain
    expect(ws.hasModules).toBe(true)
    expect(ws.layout.root?.kind).toBe('leaf')
    expect((ws.layout.root as LeafNode).moduleId).toBe('chart')
  })

  it('closing down to zero → hasModules false', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    const leafId = (ws.activeLeaf as LeafNode).id
    ws.closeLeaf(leafId)

    expect(ws.hasModules).toBe(false)
    expect(ws.layout.root).toBeNull()
    expect(ws.activeLeaf).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 4. Sidebar / autoOpen setters and persistence
// ---------------------------------------------------------------------------

describe('setSidebarWidth clamping', () => {
  it('clamps values below minimum to 200', () => {
    const ws = useWorkspaceStore()
    ws.setSidebarWidth(50)
    expect(ws.sidebarWidth).toBe(200)
  })

  it('clamps values above maximum to 420', () => {
    const ws = useWorkspaceStore()
    ws.setSidebarWidth(9999)
    expect(ws.sidebarWidth).toBe(420)
  })

  it('accepts valid values within range', () => {
    const ws = useWorkspaceStore()
    ws.setSidebarWidth(320)
    expect(ws.sidebarWidth).toBe(320)
  })
})

describe('setSidebarMode', () => {
  it('updates sidebarMode and persists to localStorage', () => {
    const ws = useWorkspaceStore()
    ws.setSidebarMode('expanded')
    expect(ws.sidebarMode).toBe('expanded')
    expect(localStorage.getItem('alice_workspace_sidebar')).toBe('expanded')
  })

  it('can set to closed', () => {
    const ws = useWorkspaceStore()
    ws.setSidebarMode('closed')
    expect(ws.sidebarMode).toBe('closed')
    expect(localStorage.getItem('alice_workspace_sidebar')).toBe('closed')
  })

  it('migrates a legacy persisted "rail" value to expanded on load', () => {
    localStorage.setItem('alice_workspace_sidebar', 'rail')
    setActivePinia(createPinia())
    const ws = useWorkspaceStore()
    expect(ws.sidebarMode).toBe('expanded')
  })
})

describe('setAutoOpen', () => {
  it('updates autoOpenEnabled and persists to localStorage', () => {
    const ws = useWorkspaceStore()
    ws.setAutoOpen(false)
    expect(ws.autoOpenEnabled).toBe(false)
    expect(localStorage.getItem('alice_workspace_autoopen')).toBe('0')
  })

  it('toggleAutoOpen flips the value and persists', () => {
    const ws = useWorkspaceStore()
    expect(ws.autoOpenEnabled).toBe(true)
    ws.toggleAutoOpen()
    expect(ws.autoOpenEnabled).toBe(false)
    expect(localStorage.getItem('alice_workspace_autoopen')).toBe('0')
    ws.toggleAutoOpen()
    expect(ws.autoOpenEnabled).toBe(true)
    expect(localStorage.getItem('alice_workspace_autoopen')).toBe('1')
  })
})

// ---------------------------------------------------------------------------
// 5. Persistence round-trip
// ---------------------------------------------------------------------------

describe('persistence round-trip', () => {
  it('restores layout from localStorage in a new store instance', () => {
    // Build a layout in the first store instance (actions persist synchronously)
    const ws1 = useWorkspaceStore()
    ws1.openModule('chart')
    ws1.openModule('cad3d')

    const persistedRaw = localStorage.getItem(LAYOUT_KEY)
    expect(persistedRaw).not.toBeNull()

    // Snapshot the layout for comparison
    const persistedLayout = JSON.parse(persistedRaw!) as unknown

    // Create a fresh Pinia but keep the same mocked localStorage
    setActivePinia(createPinia())
    const ws2 = useWorkspaceStore()

    // The new store reads from the same (still populated) localStorage shim
    expect(ws2.layout).toEqual(persistedLayout)
    expect(ws2.hasModules).toBe(true)
    expect(ws2.activeLeaf).not.toBeNull()
    expect((ws2.activeLeaf as LeafNode).moduleId).toBe('cad3d')
  })
})

// ---------------------------------------------------------------------------
// 6. migrateLayout unit tests (pure function, no store needed)
// ---------------------------------------------------------------------------

describe('migrateLayout', () => {
  it('returns empty layout when raw is not an object', () => {
    expect(migrateLayout(null)).toEqual(createEmptyLayout())
    expect(migrateLayout('string')).toEqual(createEmptyLayout())
    expect(migrateLayout(42)).toEqual(createEmptyLayout())
    expect(migrateLayout([])).toEqual(createEmptyLayout())
  })

  it('returns empty layout when version !== 1', () => {
    expect(migrateLayout({ version: 2, root: null, activeLeafId: null })).toEqual(
      createEmptyLayout()
    )
    expect(migrateLayout({ version: 0, root: null, activeLeafId: null })).toEqual(
      createEmptyLayout()
    )
    expect(migrateLayout({ version: undefined, root: null, activeLeafId: null })).toEqual(
      createEmptyLayout()
    )
  })

  it('returns empty layout when root has malformed shape', () => {
    const malformed = {
      version: 1,
      root: { kind: 'leaf', id: 'x' /* missing moduleId */ },
      activeLeafId: 'x'
    }
    expect(migrateLayout(malformed)).toEqual(createEmptyLayout())
  })

  it('returns empty layout when a leaf moduleId fails the predicate', () => {
    const layout = treeOpenModule(createEmptyLayout(), 'chart')
    const raw = JSON.parse(JSON.stringify(layout)) as unknown
    const isRegistered = (id: string): boolean => id !== 'chart' // chart is unregistered
    expect(migrateLayout(raw, isRegistered)).toEqual(createEmptyLayout())
  })

  it('preserves a valid layout with accept-all predicate', () => {
    let layout = treeOpenModule(createEmptyLayout(), 'chart')
    layout = treeOpenModule(layout, 'cad3d')
    const raw = JSON.parse(JSON.stringify(layout)) as unknown
    const result = migrateLayout(raw, () => true)
    expect(result).toEqual(layout)
  })

  it('resets activeLeafId to null when it points to a non-existent leaf', () => {
    const layout = treeOpenModule(createEmptyLayout(), 'chart')
    const raw = JSON.parse(JSON.stringify(layout)) as unknown
    // Tamper with activeLeafId
    ;(raw as Record<string, unknown>).activeLeafId = 'nonexistent-id'
    const result = migrateLayout(raw, () => true)
    expect(result.activeLeafId).toBeNull()
    // Root is still valid
    expect(result.root).not.toBeNull()
    expect((result.root as LeafNode).moduleId).toBe('chart')
  })

  it('returns empty layout for a completely empty object', () => {
    expect(migrateLayout({})).toEqual(createEmptyLayout())
  })

  it('accepts null root (no modules open) as valid', () => {
    const raw = { version: 1, root: null, activeLeafId: null }
    expect(migrateLayout(raw)).toEqual(createEmptyLayout())
  })
})

// ---------------------------------------------------------------------------
// 7b. Chat mode: tileChat / anchorChat / chatLeafId / persistence
// ---------------------------------------------------------------------------

describe('chat mode', () => {
  it('defaults to anchored with no chat leaf', () => {
    const ws = useWorkspaceStore()
    expect(ws.chatMode).toBe('anchored')
    expect(ws.chatLeafId).toBeNull()
  })

  it('tileChat sets tiled mode, persists, and opens a chat leaf when none exists', () => {
    const ws = useWorkspaceStore()
    ws.tileChat()

    expect(ws.chatMode).toBe('tiled')
    expect(localStorage.getItem('alice_workspace_chatmode')).toBe('tiled')
    expect(ws.chatLeafId).not.toBeNull()
    expect(ws.hasModules).toBe(true)
    expect((ws.layout.root as LeafNode).moduleId).toBe('chat')
  })

  it('tileChat does not open a second chat leaf when one already exists', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chat')
    const firstLeafId = ws.chatLeafId
    expect(firstLeafId).not.toBeNull()

    ws.tileChat()
    expect(ws.chatMode).toBe('tiled')
    // Same single chat leaf — no duplicate, root is still a leaf.
    expect(ws.layout.root?.kind).toBe('leaf')
    expect(ws.chatLeafId).toBe(firstLeafId)
  })

  it('chatLeafId detects the chat leaf inside a split tree', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.openModule('chat')

    expect(ws.layout.root?.kind).toBe('split')
    const leafId = ws.chatLeafId
    expect(leafId).not.toBeNull()
    // It should point at the actual chat leaf, not the chart one.
    const root = ws.layout.root as SplitNode
    const chatChild = root.children.find(
      (c) => c.kind === 'leaf' && (c as LeafNode).moduleId === 'chat'
    ) as LeafNode
    expect(leafId).toBe(chatChild.id)
  })

  it('anchorChat sets anchored mode, persists, and removes the chat leaf', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.openModule('chat')
    expect(ws.chatLeafId).not.toBeNull()

    ws.anchorChat()

    expect(ws.chatMode).toBe('anchored')
    expect(localStorage.getItem('alice_workspace_chatmode')).toBe('anchored')
    expect(ws.chatLeafId).toBeNull()
    // The chart module remains; only the chat leaf was removed.
    expect(ws.hasModules).toBe(true)
    expect((ws.layout.root as LeafNode).moduleId).toBe('chart')
  })

  it('anchorChat is a no-op on the tree when there is no chat leaf', () => {
    const ws = useWorkspaceStore()
    ws.openModule('chart')
    ws.anchorChat()

    expect(ws.chatMode).toBe('anchored')
    expect(ws.hasModules).toBe(true)
    expect((ws.layout.root as LeafNode).moduleId).toBe('chart')
  })

  it('chatMode persists across a fresh store instance', () => {
    const ws1 = useWorkspaceStore()
    ws1.tileChat()
    expect(localStorage.getItem('alice_workspace_chatmode')).toBe('tiled')

    setActivePinia(createPinia())
    const ws2 = useWorkspaceStore()
    expect(ws2.chatMode).toBe('tiled')
  })

  it('closeLeaf on the chat tile re-anchors chatMode and removes the chat leaf', () => {
    const ws = useWorkspaceStore()
    ws.tileChat()
    expect(ws.chatMode).toBe('tiled')
    const id = ws.chatLeafId
    expect(id).not.toBeNull()

    ws.closeLeaf(id as string)

    expect(ws.chatMode).toBe('anchored')
    expect(localStorage.getItem('alice_workspace_chatmode')).toBe('anchored')
    expect(ws.chatLeafId).toBeNull()
  })

  it('closeLeaf on a NON-chat tile while tiled does NOT change chatMode', () => {
    const ws = useWorkspaceStore()
    ws.tileChat()
    ws.openModule('chart')
    expect(ws.chatMode).toBe('tiled')

    // Identify the chart leaf (it will be the active leaf after the second openModule)
    const chartLeafId = (ws.activeLeaf as LeafNode).id
    expect(chartLeafId).not.toBeNull()

    ws.closeLeaf(chartLeafId)

    // chatMode must still be tiled — the chat leaf survived
    expect(ws.chatMode).toBe('tiled')
    expect(ws.chatLeafId).not.toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 7. setResizing (transient, not persisted)
// ---------------------------------------------------------------------------

describe('setResizing', () => {
  it('toggles the transient isResizing flag', () => {
    const ws = useWorkspaceStore()
    expect(ws.isResizing).toBe(false)
    ws.setResizing(true)
    expect(ws.isResizing).toBe(true)
    ws.setResizing(false)
    expect(ws.isResizing).toBe(false)
  })

  it('does not write isResizing to localStorage', () => {
    const ws = useWorkspaceStore()
    ws.setResizing(true)
    // localStorage should not have any key related to resizing
    expect(localStorage.getItem('alice_workspace_resizing')).toBeNull()
  })
})
