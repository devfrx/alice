import { describe, it, expect, beforeEach } from 'vitest'
import {
  createEmptyLayout,
  findLeaf,
  orientationOfParent,
  deepestLastLeaf,
  openModule,
  closeLeaf,
  setRatio,
  countColumns,
  columnOf
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

  it('after C: root = split(horizontal, [vSplit[A,B], leafC]); ratio 0.5; active = leafC', () => {
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    // root: horizontal spine split joining two columns
    const rootSplit = l.root as SplitNode
    expect(rootSplit.kind).toBe('split')
    expect(rootSplit.orientation).toBe('horizontal')
    expect(rootSplit.ratio).toBe(0.5)

    // children[0] = vertical split [A, B] (first column, full)
    const firstColumn = rootSplit.children[0] as SplitNode
    expect(firstColumn.kind).toBe('split')
    expect(firstColumn.orientation).toBe('vertical')
    const leafA = firstColumn.children[0] as LeafNode
    const leafB = firstColumn.children[1] as LeafNode
    expect(leafA.moduleId).toBe('moduleA')
    expect(leafB.moduleId).toBe('moduleB')

    // children[1] = leaf C (second column, single panel)
    const leafC = rootSplit.children[1] as LeafNode
    expect(leafC.kind).toBe('leaf')
    expect(leafC.moduleId).toBe('moduleC')

    expect(l.activeLeafId).toBe(leafC.id)
  })

  it('after D: root = split(horizontal, [vSplit[A,B], vSplit[C,D]]); active = leafD', () => {
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)
    l = openModule(l, 'moduleD', undefined, idGen)

    // root → horizontal spine split joining two full columns
    const rootSplit = l.root as SplitNode
    expect(rootSplit.kind).toBe('split')
    expect(rootSplit.orientation).toBe('horizontal')

    // children[0] = vertical split [A, B]
    const firstColumn = rootSplit.children[0] as SplitNode
    expect(firstColumn.kind).toBe('split')
    expect(firstColumn.orientation).toBe('vertical')
    const leafA = firstColumn.children[0] as LeafNode
    const leafB = firstColumn.children[1] as LeafNode
    expect(leafA.moduleId).toBe('moduleA')
    expect(leafB.moduleId).toBe('moduleB')

    // children[1] = vertical split [C, D] (second column, now full)
    const secondColumn = rootSplit.children[1] as SplitNode
    expect(secondColumn.kind).toBe('split')
    expect(secondColumn.orientation).toBe('vertical')
    const leafC = secondColumn.children[0] as LeafNode
    const leafD = secondColumn.children[1] as LeafNode
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
    // Build A/B/C so root = hSplit[ vSplit[A,B], leafC ]
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    // First column is vSplit[A,B]; second column is leaf C.
    const rootSplit = l.root as SplitNode
    const firstColumn = rootSplit.children[0] as SplitNode
    const leafA = firstColumn.children[0] as LeafNode
    const leafB = firstColumn.children[1] as LeafNode
    const leafC = rootSplit.children[1] as LeafNode

    // Close leaf A → A removed from its vertical column, B promoted in its place,
    // so root = hSplit[ leafB, leafC ].
    const l2 = closeLeaf(l, leafA.id)
    expect(l2.root).toEqual({
      ...rootSplit,
      children: [leafB, leafC]
    })
  })

  it('activeLeafId updates to deepestLastLeaf(sibling) when active leaf is closed', () => {
    const idGen = makeIdGen()
    let l = openModule(createEmptyLayout(), 'moduleA', undefined, idGen)
    l = openModule(l, 'moduleB', undefined, idGen)
    l = openModule(l, 'moduleC', undefined, idGen)

    // After A/B/C: root = hSplit[ vSplit[A,B], leafC ]; active = C.
    // Closing C → sibling is vSplit[A,B], deepestLastLeaf = B; activeLeafId = B.
    const rootSplit = l.root as SplitNode
    const firstColumn = rootSplit.children[0] as SplitNode
    const leafB = firstColumn.children[1] as LeafNode
    const leafC = rootSplit.children[1] as LeafNode

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
    // After A/B/C: root = hSplit[ vSplit[A,B], leafC ].
    const root = l.root as SplitNode
    const leafA = (root.children[0] as SplitNode).children[0] as LeafNode
    const leafC = root.children[1] as LeafNode
    expect(findLeaf(l.root, leafC.id)).toBe(leafC)
    expect(findLeaf(l.root, leafA.id)).toBe(leafA)
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
    // After A/B/C: root = hSplit[ vSplit[A,B], leafC ]; root.children[1] = leafC.
    const rootSplit = l.root as SplitNode
    const leafC = rootSplit.children[1] as LeafNode
    expect(deepestLastLeaf(l.root!)).toBe(leafC)
  })
})

// ---------------------------------------------------------------------------
// Column model (Task A)
// ---------------------------------------------------------------------------
describe('column model', () => {
  function build(count: number): WorkspaceLayout {
    const idGen = makeIdGen()
    let l = createEmptyLayout()
    for (let i = 0; i < count; i++) {
      l = openModule(l, `module${String.fromCharCode(65 + i)}`, undefined, idGen)
    }
    return l
  }

  it('3rd panel creates a 2nd column (root horizontal, children[1] a leaf, ratio 0.5)', () => {
    const l = build(3)
    const root = l.root as SplitNode
    expect(root.kind).toBe('split')
    expect(root.orientation).toBe('horizontal')
    expect(root.ratio).toBe(0.5)
    // children[0] is the first (full) column, children[1] is a fresh single-leaf column
    expect((root.children[0] as SplitNode).orientation).toBe('vertical')
    expect(root.children[1].kind).toBe('leaf')
  })

  it('4th panel fills the 2nd column top/bottom; root stays a single horizontal split', () => {
    const l = build(4)
    const root = l.root as SplitNode
    expect(root.kind).toBe('split')
    expect(root.orientation).toBe('horizontal')
    // NOT nested: both children are vertical-split columns, no further horizontal spine
    const left = root.children[0] as SplitNode
    const right = root.children[1] as SplitNode
    expect(left.orientation).toBe('vertical')
    expect(right.orientation).toBe('vertical')
    expect((right.children[0] as LeafNode).moduleId).toBe('moduleC')
    expect((right.children[1] as LeafNode).moduleId).toBe('moduleD')
  })

  it('5th panel creates a 3rd column with ratio 2/3 and a nested horizontal spine on the left', () => {
    const l = build(5)
    const root = l.root as SplitNode
    expect(root.kind).toBe('split')
    expect(root.orientation).toBe('horizontal')
    expect(root.ratio).toBe(2 / 3)
    // children[0] is the horizontal spine of the first two columns
    const spine = root.children[0] as SplitNode
    expect(spine.kind).toBe('split')
    expect(spine.orientation).toBe('horizontal')
    // children[1] is the fresh 3rd column (single leaf)
    expect(root.children[1].kind).toBe('leaf')
    expect((root.children[1] as LeafNode).moduleId).toBe('moduleE')
  })

  it('countColumns returns 1/1/2/2/3 after A/B/C/D/E', () => {
    expect(countColumns(build(1).root!)).toBe(1)
    expect(countColumns(build(2).root!)).toBe(1)
    expect(countColumns(build(3).root!)).toBe(2)
    expect(countColumns(build(4).root!)).toBe(2)
    expect(countColumns(build(5).root!)).toBe(3)
  })

  it('columnOf returns the column node containing a given active leaf', () => {
    // After A/B/C/D/E: root = hSplit[ hSplit[vSplit[A,B], vSplit[C,D]], leafE ].
    const l = build(5)
    const root = l.root as SplitNode
    const spine = root.children[0] as SplitNode
    const colAB = spine.children[0] as SplitNode // vSplit[A,B]
    const colCD = spine.children[1] as SplitNode // vSplit[C,D]
    const leafE = root.children[1] as LeafNode

    const leafA = colAB.children[0] as LeafNode
    const leafD = colCD.children[1] as LeafNode

    expect(columnOf(root, leafA.id)).toBe(colAB)
    expect(columnOf(root, leafD.id)).toBe(colCD)
    expect(columnOf(root, leafE.id)).toBe(leafE)
  })
})
