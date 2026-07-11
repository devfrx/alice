import type {
  LeafNode,
  SplitNode,
  SplitOrientation,
  TileNode,
  WorkspaceLayout
} from './tilingTypes'

// ---------------------------------------------------------------------------
// Id generation
// ---------------------------------------------------------------------------

export type IdGen = () => string

let _counter = 0
const defaultIdGen: IdGen = () => `tile-${++_counter}`

// ---------------------------------------------------------------------------
// Internal node constructors (NOT exported — keep nodes plain-JSON)
// ---------------------------------------------------------------------------

function makeLeaf(
  moduleId: string,
  params: Record<string, unknown> | undefined,
  id: string
): LeafNode {
  const node: LeafNode = { kind: 'leaf', id, moduleId }
  if (params !== undefined) node.params = params
  return node
}

function makeSplit(
  orientation: SplitOrientation,
  ratio: number,
  children: [TileNode, TileNode],
  id: string
): SplitNode {
  return { kind: 'split', id, orientation, ratio, children }
}

// ---------------------------------------------------------------------------
// Public pure functions
// ---------------------------------------------------------------------------

export function createEmptyLayout(): WorkspaceLayout {
  return { version: 1, root: null, activeLeafId: null }
}

/** Find a leaf by id within a subtree. Returns null if not found. */
export function findLeaf(root: TileNode | null, leafId: string): LeafNode | null {
  if (root === null) return null
  if (root.kind === 'leaf') return root.id === leafId ? root : null
  return findLeaf(root.children[0], leafId) ?? findLeaf(root.children[1], leafId)
}

/** Returns the orientation of the split node that directly contains leafId.
 *  Returns null if the leaf is the root itself, or not found. */
export function orientationOfParent(
  root: TileNode | null,
  leafId: string
): SplitOrientation | null {
  if (root === null) return null
  if (root.kind === 'leaf') return null // leaf is root → no parent
  return _findParentOrientation(root, leafId)
}

function _findParentOrientation(node: SplitNode, leafId: string): SplitOrientation | null {
  for (const child of node.children) {
    if (child.kind === 'leaf' && child.id === leafId) {
      return node.orientation
    }
    if (child.kind === 'split') {
      const found = _findParentOrientation(child, leafId)
      if (found !== null) return found
    }
  }
  return null
}

/** Follow children[1] recursively until reaching a leaf. */
export function deepestLastLeaf(node: TileNode): LeafNode {
  if (node.kind === 'leaf') return node
  return deepestLastLeaf(node.children[1])
}

/** Count the columns in a subtree.
 *  A `horizontal` split is part of the top-level spine → sum of its children's
 *  column counts. Any other node (a `leaf` or a `vertical` split) IS a single
 *  column. */
export function countColumns(node: TileNode): number {
  if (node.kind === 'split' && node.orientation === 'horizontal') {
    return countColumns(node.children[0]) + countColumns(node.children[1])
  }
  return 1
}

/** Walk down the top-level `horizontal` spine toward the leaf, returning the
 *  first node that is the column containing it (a `leaf` or a `vertical` split).
 *  Assumes leafId exists within `root`. */
export function columnOf(root: TileNode, leafId: string): TileNode {
  let node = root
  while (node.kind === 'split' && node.orientation === 'horizontal') {
    node = findLeaf(node.children[0], leafId) !== null ? node.children[0] : node.children[1]
  }
  return node
}

/** Open a new module under the strict column model.
 *  A column holds at most 2 panels (a single leaf, or a `vertical` split of two
 *  leaves stacked top/bottom). The top-level spine is `horizontal` splits joining
 *  columns left-to-right.
 *  Returns a new WorkspaceLayout; inputs are never mutated. */
export function openModule(
  layout: WorkspaceLayout,
  moduleId: string,
  params?: Record<string, unknown>,
  idGen: IdGen = defaultIdGen
): WorkspaceLayout {
  const newLeaf = makeLeaf(moduleId, params, idGen())

  if (layout.root === null) {
    return { ...layout, root: newLeaf, activeLeafId: newLeaf.id }
  }

  const target =
    (layout.activeLeafId !== null ? findLeaf(layout.root, layout.activeLeafId) : null) ??
    deepestLastLeaf(layout.root)

  const column = columnOf(layout.root, target.id)

  if (column.kind === 'leaf') {
    // Column has room (1 panel) → stack the new leaf below it (top/bottom).
    const splitId = idGen()
    const newColumn = makeSplit('vertical', 0.5, [column, newLeaf], splitId)
    const newRoot = _replaceNode(layout.root, column.id, newColumn)
    return { ...layout, root: newRoot, activeLeafId: newLeaf.id }
  }

  // Column is full (a vertical split of 2 panels) → append a fresh column on the
  // far right by replacing the entire root with a horizontal spine split.
  const n = countColumns(layout.root)
  const splitId = idGen()
  const newRoot = makeSplit('horizontal', n / (n + 1), [layout.root, newLeaf], splitId)
  return { ...layout, root: newRoot, activeLeafId: newLeaf.id }
}

/** Replace the node with the given id in the subtree, returning a new subtree.
 *  Untouched subtrees are structurally shared. */
function _replaceNode(node: TileNode, targetId: string, replacement: TileNode): TileNode {
  if (node.id === targetId) return replacement
  if (node.kind === 'leaf') return node
  const [c0, c1] = node.children
  const newC0 = _replaceNode(c0, targetId, replacement)
  const newC1 = _replaceNode(c1, targetId, replacement)
  if (newC0 === c0 && newC1 === c1) return node
  return { ...node, children: [newC0, newC1] }
}

/** Close a leaf. If it is the root → root becomes null.
 *  Otherwise the parent split is replaced by the sibling subtree.
 *  activeLeafId is updated if it pointed to the closed leaf. */
export function closeLeaf(layout: WorkspaceLayout, leafId: string): WorkspaceLayout {
  if (layout.root === null) return layout

  // Closing the root leaf
  if (layout.root.kind === 'leaf' && layout.root.id === leafId) {
    return { ...layout, root: null, activeLeafId: null }
  }

  if (layout.root.kind === 'leaf') return layout // leafId not found

  const result = _removeLeaf(layout.root, leafId)
  if (result === null) return layout // not found

  const [newRoot, sibling] = result
  let newActiveLeafId = layout.activeLeafId
  if (newActiveLeafId === leafId) {
    newActiveLeafId = deepestLastLeaf(sibling).id
  }

  return { ...layout, root: newRoot, activeLeafId: newActiveLeafId }
}

/**
 * Remove the leaf with leafId from the split subtree.
 * Returns [newRoot, promotedSibling] or null if not found.
 * promotedSibling is the sibling that replaced the parent split.
 */
function _removeLeaf(node: SplitNode, leafId: string): [TileNode, TileNode] | null {
  for (let i = 0; i < 2; i++) {
    const child = node.children[i]
    const sibling = node.children[1 - i]

    if (child.kind === 'leaf' && child.id === leafId) {
      // This split node is the direct parent: replace it with sibling
      return [sibling, sibling]
    }

    if (child.kind === 'split') {
      const inner = _removeLeaf(child, leafId)
      if (inner !== null) {
        const [newChild, promoted] = inner
        const newChildren: [TileNode, TileNode] =
          i === 0 ? [newChild, sibling] : [sibling, newChild]
        const newNode: SplitNode = { ...node, children: newChildren }
        return [newNode, promoted]
      }
    }
  }
  return null
}

/** Update the ratio of a split node (clamped to [0.1, 0.9]).
 *  Returns a new layout; inputs are never mutated. */
export function setRatio(layout: WorkspaceLayout, splitId: string, ratio: number): WorkspaceLayout {
  if (layout.root === null) return layout
  const clamped = Math.min(0.9, Math.max(0.1, ratio))
  const newRoot = _updateRatio(layout.root, splitId, clamped)
  if (newRoot === layout.root) return layout
  return { ...layout, root: newRoot }
}

function _updateRatio(node: TileNode, splitId: string, ratio: number): TileNode {
  if (node.kind === 'leaf') return node
  if (node.id === splitId) return { ...node, ratio }
  const [c0, c1] = node.children
  const newC0 = _updateRatio(c0, splitId, ratio)
  const newC1 = _updateRatio(c1, splitId, ratio)
  if (newC0 === c0 && newC1 === c1) return node
  return { ...node, children: [newC0, newC1] }
}
