/**
 * useArtifactAutoOpen.spec.ts
 *
 * Unit tests for the auto-open composable.
 *
 * Strategy: test the pure helpers (isNewId, diffNewIds) exhaustively, then
 * wire up a lightweight integration test that exercises the intent bus end-to-
 * end (emit → handler → store.openModule) by constructing a fresh Pinia and
 * directly calling emitOpenModule with a handler registered via onOpenModule.
 *
 * The Vue watcher wiring cannot be exercised without mounting a component, so
 * we concentrate unit coverage on the logic that CAN be tested in isolation.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { isNewId, diffNewIds } from './useArtifactAutoOpen'
import { emitOpenModule, onOpenModule, _clearOpenModuleHandlers } from './moduleIntents'
import { useWorkspaceStore } from '../../stores/workspace'

// ---------------------------------------------------------------------------
// Helpers: localStorage shim (same pattern as workspace.spec.ts)
// ---------------------------------------------------------------------------

function makeLocalStorageShim(): {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
  clear: () => void
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
    }
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('localStorage', makeLocalStorageShim())
  _clearOpenModuleHandlers()
})

// ---------------------------------------------------------------------------
// 1. Pure helpers
// ---------------------------------------------------------------------------

describe('isNewId', () => {
  it('returns true when id is absent from seen', () => {
    const seen = new Set<string>(['a', 'b'])
    expect(isNewId(seen, 'c')).toBe(true)
  })

  it('returns false when id is already in seen', () => {
    const seen = new Set<string>(['a', 'b'])
    expect(isNewId(seen, 'a')).toBe(false)
  })

  it('does not mutate the seen set', () => {
    const seen = new Set<string>(['a'])
    isNewId(seen, 'b')
    expect(seen.size).toBe(1)
  })

  it('works with an empty seen set', () => {
    expect(isNewId(new Set(), 'anything')).toBe(true)
  })
})

describe('diffNewIds', () => {
  it('returns ids present in current but missing from seen', () => {
    const seen = new Set<string>(['a', 'b'])
    expect(diffNewIds(seen, ['a', 'b', 'c', 'd'])).toEqual(['c', 'd'])
  })

  it('returns an empty array when all ids are already seen', () => {
    const seen = new Set<string>(['x', 'y'])
    expect(diffNewIds(seen, ['x', 'y'])).toEqual([])
  })

  it('returns all ids when seen is empty', () => {
    expect(diffNewIds(new Set(), ['p', 'q'])).toEqual(['p', 'q'])
  })

  it('returns an empty array when current is empty', () => {
    const seen = new Set<string>(['a'])
    expect(diffNewIds(seen, [])).toEqual([])
  })

  it('does not mutate the seen set', () => {
    const seen = new Set<string>(['a'])
    diffNewIds(seen, ['b'])
    expect(seen.size).toBe(1)
  })
})

// ---------------------------------------------------------------------------
// 2. Intent bus → store routing (integration, no component mount)
// ---------------------------------------------------------------------------

describe('intent bus → workspace store integration', () => {
  it('calling emitOpenModule invokes a registered handler once', () => {
    const received: Array<{ moduleId: string; params?: Record<string, unknown> }> = []

    onOpenModule(({ moduleId, params }) => {
      received.push({ moduleId, params })
    })

    emitOpenModule('chart', {
      chartPayload: {
        chart_id: 'ch1',
        chart_url: '/api/charts/ch1',
        title: 'Test Chart',
        chart_type: 'bar',
        created_at: '2024-01-01T00:00:00Z'
      }
    })

    expect(received).toHaveLength(1)
    expect(received[0].moduleId).toBe('chart')
    expect(received[0].params?.chartPayload).toMatchObject({ chart_id: 'ch1' })
  })

  it('handler receives correct params for cad3d', () => {
    const received: Array<{ moduleId: string; params?: Record<string, unknown> }> = []
    onOpenModule(({ moduleId, params }) => received.push({ moduleId, params }))

    emitOpenModule('cad3d', { artifactId: 'artifact-uuid-123' })

    expect(received[0].moduleId).toBe('cad3d')
    expect(received[0].params?.artifactId).toBe('artifact-uuid-123')
  })

  it('handler receives correct params for whiteboard', () => {
    const received: Array<{ moduleId: string; params?: Record<string, unknown> }> = []
    onOpenModule(({ moduleId, params }) => received.push({ moduleId, params }))

    emitOpenModule('whiteboard', { boardId: 'board-uuid-456' })

    expect(received[0].moduleId).toBe('whiteboard')
    expect(received[0].params?.boardId).toBe('board-uuid-456')
  })

  it('unsubscribed handler is NOT called after unsubscribe', () => {
    const count = vi.fn()
    const unsub = onOpenModule(() => count())

    emitOpenModule('chart')
    expect(count).toHaveBeenCalledTimes(1)

    unsub()
    emitOpenModule('chart')
    expect(count).toHaveBeenCalledTimes(1) // still 1
  })

  it('workspace store openModule is called when intent is emitted and autoOpen is on', () => {
    const ws = useWorkspaceStore()

    expect(ws.autoOpenEnabled).toBe(true)

    // Simulate what PanelWorkspace does: subscribe and forward to the store.
    const unsub = onOpenModule(({ moduleId, params }) => {
      if (ws.autoOpenEnabled) ws.openModule(moduleId, params)
    })

    emitOpenModule('chart', {
      chartPayload: {
        chart_id: 'c1',
        chart_url: '/api/charts/c1',
        title: 'T',
        chart_type: 'line',
        created_at: ''
      }
    })

    expect(ws.layout.root).not.toBeNull()
    // The opened leaf should be a chart module.
    const root = ws.layout.root
    expect(root?.kind).toBe('leaf')
    if (root && root.kind === 'leaf') {
      expect(root.moduleId).toBe('chart')
    }

    unsub()
  })

  it('workspace store openModule is NOT called when autoOpen is disabled', () => {
    const ws = useWorkspaceStore()
    ws.setAutoOpen(false)

    const openSpy = vi.spyOn(ws, 'openModule')

    // Simulate the PanelWorkspace consumer.
    const unsub = onOpenModule(({ moduleId, params }) => {
      if (ws.autoOpenEnabled) ws.openModule(moduleId, params)
    })

    emitOpenModule('cad3d', { artifactId: 'some-id' })

    expect(openSpy).not.toHaveBeenCalled()

    unsub()
  })
})

// ---------------------------------------------------------------------------
// 3. Dedup: the same id must not trigger a second emit
// ---------------------------------------------------------------------------

describe('dedup logic via isNewId + Set', () => {
  it('marks an id as seen and prevents re-emission', () => {
    const seen = new Set<string>()
    const emitted: string[] = []

    function maybeEmit(id: string): void {
      if (!isNewId(seen, id)) return
      seen.add(id)
      emitted.push(id)
    }

    maybeEmit('chart-1')
    maybeEmit('chart-1') // duplicate
    maybeEmit('chart-2')

    expect(emitted).toEqual(['chart-1', 'chart-2'])
    expect(seen.size).toBe(2)
  })

  it('initial backlog does not re-emit when seeded into seen', () => {
    // Simulate: at mount time, seed from existing items.
    const existingIds = ['art-1', 'art-2', 'art-3']
    const seen = new Set<string>(existingIds)
    const emitted: string[] = []

    // New item arrives after mount.
    const incoming = ['art-1', 'art-2', 'art-3', 'art-4']
    for (const id of incoming) {
      if (!isNewId(seen, id)) continue
      seen.add(id)
      emitted.push(id)
    }

    // Only art-4 is new; the backlog is silent.
    expect(emitted).toEqual(['art-4'])
  })
})
