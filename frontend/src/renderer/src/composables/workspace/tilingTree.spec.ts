import { describe, it, expect, beforeEach } from 'vitest'
import {
  createEmptyLayout,
  findLeaf,
  orientationOfParent,
  deepestLastLeaf,
  openModule,
  closeLeaf,
  setRatio
} from './tilingTree'
import type { LeafNode, SplitNode, WorkspaceLayout } from './tilingTypes'

// ---------------------------------------------------------------------------
// Deterministic id generator factory
// ---------------------------------------------------------------------------
function makeIdGen(prefix = 'id'): () => string {
  let n = 0
  return () => `${prefix}-${++n}`
}

// ---------------------------------------------------------------------------
// 1. createEmptyLayout shape
// ---------------------------------------------------------------------------
describe('createEmptyLayout', () => {
  it('returns the expected shape', () => {
    const layout = createEmptyLayout()
    expect(layout).toEqual({ version: 1, root: null, activeLeafId: null })
  })
})

// ---------------------------------------------------------------------------
// 2. openModule on empty layout
// ---------------------------------------------------------------------------
describe('openModule on empty layout', () => {
  it('creates a root leaf with the moduleId and sets activeLeafId', () => {
    const idGen = makeIdGen()
    const layout = openModule(createEmptyLayout(), 'chat', undefined, idGen)
    expect(layout.root).not.toBeNull()
    const root = layout.root as LeafNode
    expect(root.kind).toBe('leaf')
    expect(root.moduleId).toBe('chat')
    expect(layout.activeLeafId).toBe(root.id)
  })
})

// ---------------------------------------------------------------------------
// 3. Four-step A → B → C → D sequence
// ---------------------------------------------------------------------------
describe('4-step A/B/C/D sequence', () => {
  let idGen: () => string

  // We use a fresh idGen per test so ids are predictable.
  // The openModule call uses idGen() for the leaf, then idGen() for the split.
  // On an empty layout only one id is consumed (the leaf; no split needed).
  //
  // Step A: idGen called once  → leaf id = "id-1"           (A leaf)
  // Step B: idGen called twice → leaf id = "id-2", split id = "id-3"
  // Step C: idGen called twice → leaf id = "id-4", split id = "id-5"
  // Step D: idGen called twice → leaf id = "id-6", split id = "id-7"

  beforeEach(() => {
    idGen = makeIdGen()
  })

  it('after A: root is a leaf for "moduleA"', () => {
    const l1 = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    const root = l1.root as LeafNode
    expect(root.kind).toBe('leaf')
    expect(root.moduleId).toBe('moduleA')
    expect(root.id).toBe('id-1')
    expect(l1.activeLeafId).toBe('id-1')
  })

  it('after B: root is split(vertical, [leafA, leafB]); active = leafB', () => {
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen) // A
    l = openModule(l, 'moduleB', undefined, idGen) // B

    // root should be a vertical split
    const split = l.root as SplitNode
    expect(split.kind).toBe('split')
    expect(split.orientation).toBe('vertical')
    expect(split.ratio).toBe(0.5)

    // children[0] = leaf A, children[1] = leaf B
    const leafA = split.children[0] as LeafNode
    const leafB = split.children[1] as LeafNode
    expect(leafA.kind).toBe('leaf')
    expect(leafA.moduleId).toBe('moduleA')
    expect(leafB.kind).toBe('leaf')
    expect(leafB.moduleId).toBe('moduleB')

    // active is leafB
    expect(l.activeLeafId).toBe(leafB.id)
  })

  it('after C: root = split(vertical, [leafA, split(horizontal, [leafB, leafC])]); active = leafC', () => {
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    // root: vertical split
    const rootSplit = l.root as SplitNode
    expect(rootSplit.kind).toBe('split')
    expect(rootSplit.orientation).toBe('vertical')

    // children[0] = leaf A (unchanged)
    const leafA = rootSplit.children[0] as LeafNode
    expect(leafA.kind).toBe('leaf')
    expect(leafA.moduleId).toBe('moduleA')

    // children[1] = horizontal split containing B and C
    const innerSplit = rootSplit.children[1] as SplitNode
    expect(innerSplit.kind).toBe('split')
    expect(innerSplit.orientation).toBe('horizontal')

    const leafB = innerSplit.children[0] as LeafNode
    const leafC = innerSplit.children[1] as LeafNode
    expect(leafB.kind).toBe('leaf')
    expect(leafB.moduleId).toBe('moduleB')
    expect(leafC.kind).toBe('leaf')
    expect(leafC.moduleId).toBe('moduleC')

    expect(l.activeLeafId).toBe(leafC.id)
  })

  it('after D: C replaced by split(vertical, [leafC, leafD]); active = leafD', () => {
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)
    l = openModule(l, 'moduleD', undefined, idGen)

    // root → vertical split
    const rootSplit = l.root as SplitNode
    expect(rootSplit.kind).toBe('split')
    expect(rootSplit.orientation).toBe('vertical')

    // children[0] = leaf A
    const leafA = rootSplit.children[0] as LeafNode
    expect(leafA.moduleId).toBe('moduleA')

    // children[1] = horizontal split [B, split(vertical, [C, D])]
    const mid = rootSplit.children[1] as SplitNode
    expect(mid.kind).toBe('split')
    expect(mid.orientation).toBe('horizontal')

    const leafB = mid.children[0] as LeafNode
    expect(leafB.moduleId).toBe('moduleB')

    const rightSplit = mid.children[1] as SplitNode
    expect(rightSplit.kind).toBe('split')
    expect(rightSplit.orientation).toBe('vertical')

    const leafC = rightSplit.children[0] as LeafNode
    const leafD = rightSplit.children[1] as LeafNode
    expect(leafC.moduleId).toBe('moduleC')
    expect(leafD.moduleId).toBe('moduleD')

    expect(l.activeLeafId).toBe(leafD.id)
  })
})

// ---------------------------------------------------------------------------
// 4. closeLeaf behaviour
// ---------------------------------------------------------------------------
describe('closeLeaf', () => {
  it('closing the root leaf → root null, activeLeafId null', () => {
    const idGen = makeIdGen()
    const l1 = openModule(createEmptyLayout(), 'chat', undefined, idGen)
    const rootLeaf = l1.root as LeafNode
    const l2 = closeLeaf(l1, rootLeaf.id)
    expect(l2.root).toBeNull()
    expect(l2.activeLeafId).toBeNull()
  })

  it('closing A from A/B vertical split → root becomes leaf B; activeLeafId = B', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)

    const split = l.root as SplitNode
    const leafA = split.children[0] as LeafNode
    const leafB = split.children[1] as LeafNode

    const l2 = closeLeaf(l, leafA.id)
    expect(l2.root).toEqual(leafB)
    expect(l2.activeLeafId).toBe(leafB.id)
  })

  it('closing B from A/B vertical split → root becomes leaf A; activeLeafId = A', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)

    const split = l.root as SplitNode
    const leafA = split.children[0] as LeafNode
    const leafB = split.children[1] as LeafNode

    const l2 = closeLeaf(l, leafB.id)
    expect(l2.root).toEqual(leafA)
    expect(l2.activeLeafId).toBe(leafA.id)
  })

  it('closing a leaf whose sibling is a subtree promotes the sibling subtree', () => {
    const idGen = makeIdGen()
    // Build A/B/C so root = split(vertical, [A, split(horizontal, [B, C])])
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    const rootSplit = l.root as SplitNode
    const leafA = rootSplit.children[0] as LeafNode
    const innerSplit = rootSplit.children[1] as SplitNode

    // Close leaf A → root should be the inner horizontal split
    const l2 = closeLeaf(l, leafA.id)
    expect(l2.root).toEqual(innerSplit)
  })

  it('activeLeafId updates to deepestLastLeaf(sibling) when active leaf is closed', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    // active = C; close C → sibling is B; activeLeafId should be B
    const rootSplit = l.root as SplitNode
    const innerSplit = rootSplit.children[1] as SplitNode
    const leafB = innerSplit.children[0] as LeafNode
    const leafC = innerSplit.children[1] as LeafNode

    expect(l.activeLeafId).toBe(leafC.id)
    const l2 = closeLeaf(l, leafC.id)
    expect(l2.activeLeafId).toBe(leafB.id)
  })
})

// ---------------------------------------------------------------------------
// 5. setRatio clamping
// ---------------------------------------------------------------------------
describe('setRatio', () => {
  function buildLayout(): { layout: WorkspaceLayout; splitId: string } {
    const idGen = makeIdGen()
    let layout = openModule(createEmptyLayout(), 'A', undefined, idGen)
    layout = openModule(layout, 'B', undefined, idGen)
    const splitId = (layout.root as SplitNode).id
    return { layout, splitId }
  }

  it('clamps ratio below 0.1 to 0.1', () => {
    const { layout, splitId } = buildLayout()
    const l2 = setRatio(layout, splitId, 0.0)
    expect((l2.root as SplitNode).ratio).toBe(0.1)
  })

  it('clamps ratio above 0.9 to 0.9', () => {
    const { layout, splitId } = buildLayout()
    const l2 = setRatio(layout, splitId, 1.0)
    expect((l2.root as SplitNode).ratio).toBe(0.9)
  })

  it('allows valid ratio in range', () => {
    const { layout, splitId } = buildLayout()
    const l2 = setRatio(layout, splitId, 0.65)
    expect((l2.root as SplitNode).ratio).toBe(0.65)
  })
})

// ---------------------------------------------------------------------------
// 6. Purity: original layout not mutated
// ---------------------------------------------------------------------------
describe('purity', () => {
  it('openModule does not mutate the original layout', () => {
    const idGen = makeIdGen()
    const l1 = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    const snapshot = JSON.parse(JSON.stringify(l1)) as WorkspaceLayout
    openModule(l1, 'moduleB', undefined, idGen)
    expect(l1).toEqual(snapshot)
  })

  it('closeLeaf does not mutate the original layout', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    const snapshot = JSON.parse(JSON.stringify(l)) as WorkspaceLayout
    const leafA = (l.root as SplitNode).children[0] as LeafNode
    closeLeaf(l, leafA.id)
    expect(l).toEqual(snapshot)
  })
})

// ---------------------------------------------------------------------------
// 7. Round-trip JSON serialization
// ---------------------------------------------------------------------------
describe('JSON round-trip', () => {
  it('layout survives JSON.parse(JSON.stringify(layout)) without loss', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)
    const roundTripped = JSON.parse(JSON.stringify(l)) as WorkspaceLayout
    expect(roundTripped).toEqual(l)
  })
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
describe('findLeaf', () => {
  it('returns null when root is null', () => {
    expect(findLeaf(null, 'any')).toBeNull()
  })

  it('finds a leaf in a nested tree', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'A', undefined, idGen)
    l = openModule(l, 'B', undefined, idGen)
    l = openModule(l, 'C', undefined, idGen)
    const root = l.root as SplitNode
    const innerSplit = root.children[1] as SplitNode
    const leafC = innerSplit.children[1] as LeafNode
    expect(findLeaf(l.root, leafC.id)).toBe(leafC)
  })
})

describe('orientationOfParent', () => {
  it('returns null for a lone root leaf', () => {
    const idGen = makeIdGen()
    const l = openModule(createEmptyLayout(), 'A', undefined, idGen)
    const root = l.root as LeafNode
    expect(orientationOfParent(l.root, root.id)).toBeNull()
  })

  it('returns orientation of the parent split', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'A', undefined, idGen)
    l = openModule(l, 'B', undefined, idGen)
    const split = l.root as SplitNode
    const leafA = split.children[0] as LeafNode
    expect(orientationOfParent(l.root, leafA.id)).toBe('vertical')
  })
})

describe('deepestLastLeaf', () => {
  it('returns the node itself for a leaf', () => {
    const idGen = makeIdGen()
    const l = openModule(createEmptyLayout(), 'A', undefined, idGen)
    const root = l.root as LeafNode
    expect(deepestLastLeaf(root)).toBe(root)
  })

  it('follows children[1] down to the deepest leaf', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'A', undefined, idGen)
    l = openModule(l, 'B', undefined, idGen)
    l = openModule(l, 'C', undefined, idGen)
    // deepest last leaf from root: root.children[1] is split, its children[1] = leafC
    const rootSplit = l.root as SplitNode
    const innerSplit = rootSplit.children[1] as SplitNode
    const leafC = innerSplit.children[1] as LeafNode
    expect(deepestLastLeaf(l.root!)).toBe(leafC)
  })
})
