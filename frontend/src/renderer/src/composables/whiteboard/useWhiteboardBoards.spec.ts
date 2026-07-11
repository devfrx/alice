import { describe, it, expect } from 'vitest'
import { toBoardItem } from './useWhiteboardBoards'
import type { Artifact } from '../../types/artifacts'

const art = {
  id: 'a1',
  kind: 'whiteboard',
  title: 'Board',
  conversation_id: 'c1',
  artifact_metadata: { shape_count: 3, description: '' },
  created_at: '2026-06-12T00:00:00Z',
  updated_at: '2026-06-12T01:00:00Z',
  file_path: 'data/artifacts/whiteboard/a1.json',
  mime: 'application/json',
  size_bytes: 10,
  download_url: '/api/artifacts/a1/download'
} as unknown as Artifact

describe('toBoardItem', () => {
  it('maps registry metadata to the board view-model', () => {
    const item = toBoardItem(art, (id) => (id === 'c1' ? 'Conv' : null))
    expect(item.boardId).toBe('a1')
    expect(item.shapeCount).toBe(3)
    expect(item.conversationTitle).toBe('Conv')
    expect(item.updatedAt).toBe('2026-06-12T01:00:00Z')
  })

  it('defaults shapeCount to 0 and titles to null when metadata is missing', () => {
    const bare = {
      ...art,
      artifact_metadata: undefined,
      conversation_id: null
    } as unknown as Artifact
    const item = toBoardItem(bare, () => null)
    expect(item.shapeCount).toBe(0)
    expect(item.conversationTitle).toBeNull()
  })
})
