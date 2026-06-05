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

/** Open a new module, splitting the active (or deepest-last) leaf.
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

  const parentOrient = orientationOfParent(layout.root, target.id)
  const newOrient: SplitOrientation =
    parentOrient === null ? 'vertical' : parentOrient === 'vertical' ? 'horizontal' : 'vertical'

  const splitId = idGen()
  const newSplit = makeSplit(newOrient, 0.5, [target, newLeaf], splitId)

  const newRoot = _replaceNode(layout.root, target.id, newSplit)
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
