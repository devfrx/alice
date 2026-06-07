/**
 * useModuleItemSelection.spec.ts
 *
 * Unit tests for the shared multi-item selection logic used by the workspace
 * chart / whiteboard / 3D module tiles. Exercised directly (computed + watch
 * work outside a component); async param updates are awaited via nextTick.
 */
import { describe, it, expect } from 'vitest'
import { ref, nextTick } from 'vue'
import { useModuleItemSelection } from './useModuleItemSelection'

interface Item {
  id: string
  name: string
}

const list = (...ids: string[]): Item[] => ids.map((id) => ({ id, name: id.toUpperCase() }))

describe('useModuleItemSelection', () => {
  it('returns null when the list is empty', () => {
    const items = ref<Item[]>([])
    const sel = useModuleItemSelection<Item>({ items: () => items.value, getId: (i) => i.id })
    expect(sel.current.value).toBeNull()
    expect(sel.currentId.value).toBeNull()
  })

  it('defaults to the most-recent (last) item', () => {
    const items = ref(list('a', 'b', 'c'))
    const sel = useModuleItemSelection<Item>({ items: () => items.value, getId: (i) => i.id })
    expect(sel.currentId.value).toBe('c')
  })

  it('adopts the preferred (param) id on creation', () => {
    const items = ref(list('a', 'b', 'c'))
    const sel = useModuleItemSelection<Item>({
      items: () => items.value,
      getId: (i) => i.id,
      preferredId: () => 'a',
    })
    expect(sel.currentId.value).toBe('a')
  })

  it('lets a manual select() override the default', () => {
    const items = ref(list('a', 'b', 'c'))
    const sel = useModuleItemSelection<Item>({ items: () => items.value, getId: (i) => i.id })
    sel.select('b')
    expect(sel.currentId.value).toBe('b')
  })

  it('manual select wins over the preferred id', () => {
    const items = ref(list('a', 'b', 'c'))
    const sel = useModuleItemSelection<Item>({
      items: () => items.value,
      getId: (i) => i.id,
      preferredId: () => 'a',
    })
    sel.select('c')
    expect(sel.currentId.value).toBe('c')
  })

  it('falls back to latest when the selection becomes stale', () => {
    const items = ref(list('a', 'b', 'c'))
    const sel = useModuleItemSelection<Item>({ items: () => items.value, getId: (i) => i.id })
    sel.select('b')
    expect(sel.currentId.value).toBe('b')
    // 'b' removed → selection is stale → fall back to the latest remaining item.
    items.value = list('a', 'c')
    expect(sel.currentId.value).toBe('c')
  })

  it('reacts when the preferred id changes after creation', async () => {
    const items = ref(list('a', 'b', 'c'))
    const pref = ref<string | null>(null)
    const sel = useModuleItemSelection<Item>({
      items: () => items.value,
      getId: (i) => i.id,
      preferredId: () => pref.value,
    })
    expect(sel.currentId.value).toBe('c') // no preference yet → latest
    pref.value = 'a'
    await nextTick()
    expect(sel.currentId.value).toBe('a')
  })

  it('keeps a valid manual selection when newer items arrive', () => {
    const items = ref(list('a', 'b'))
    const sel = useModuleItemSelection<Item>({ items: () => items.value, getId: (i) => i.id })
    sel.select('a')
    items.value = list('a', 'b', 'c') // new chart generated
    expect(sel.currentId.value).toBe('a') // user's pick is preserved
  })
})
