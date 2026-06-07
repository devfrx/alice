export type SplitOrientation = 'horizontal' | 'vertical'
// horizontal = children side-by-side (a vertical divider between them)
// vertical   = children stacked top/bottom (a horizontal divider)

export interface SplitNode {
  kind: 'split'
  id: string
  orientation: SplitOrientation
  ratio: number // first child's main-axis fraction, clamped [0.1, 0.9]
  children: [TileNode, TileNode] // strictly binary
}

export interface LeafNode {
  kind: 'leaf'
  id: string
  moduleId: string
  params?: Record<string, unknown>
}

export type TileNode = SplitNode | LeafNode

export interface WorkspaceLayout {
  version: 1
  root: TileNode | null // null = no modules open (chat owns the area)
  activeLeafId: string | null
}
