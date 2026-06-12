/**
 * useWhiteboardBoards — shared view-model for whiteboards-as-artifacts.
 *
 * Derives the board list from the unified artifacts store
 * (kind='whiteboard'), mapping registry metadata (shape_count) and
 * resolving the conversation title from the chat store. Replaces the
 * retired 'whiteboard' Pinia store.
 */
import { computed, type ComputedRef } from 'vue'
import { useArtifactsStore } from '../../stores/artifacts'
import { useChatStore } from '../../stores/chat'
import type { Artifact } from '../../types/artifacts'

export interface WhiteboardBoardItem {
  /** Artifact id (the old board_id). */
  boardId: string
  title: string
  conversationId: string | null
  conversationTitle: string | null
  shapeCount: number
  /** ISO 8601 datetime. */
  updatedAt: string
}

/** Pure mapping Artifact → board view-model (exported for tests). */
export function toBoardItem(
  a: Artifact,
  titleOf: (id: string | null) => string | null,
): WhiteboardBoardItem {
  const meta = a.artifact_metadata ?? {}
  const convId = a.conversation_id ?? null
  return {
    boardId: a.id,
    title: a.title,
    conversationId: convId,
    conversationTitle: titleOf(convId),
    shapeCount: typeof meta.shape_count === 'number' ? meta.shape_count : 0,
    updatedAt: a.updated_at,
  }
}

export function useWhiteboardBoards(
  conversationId?: () => string | null | undefined,
): {
  boards: ComputedRef<WhiteboardBoardItem[]>
  loading: ComputedRef<boolean>
  refresh: () => Promise<void>
} {
  const artifactsStore = useArtifactsStore()
  const chatStore = useChatStore()

  function titleOf(id: string | null): string | null {
    if (!id) return null
    return chatStore.conversations.find((c) => c.id === id)?.title ?? null
  }

  const boards = computed<WhiteboardBoardItem[]>(() => {
    const convId = conversationId?.()
    return artifactsStore.items
      .filter((a) => a.kind === 'whiteboard')
      .filter((a) => (convId ? a.conversation_id === convId : true))
      .map((a) => toBoardItem(a, titleOf))
  })

  async function refresh(): Promise<void> {
    const convId = conversationId?.()
    await artifactsStore.fetch({
      kind: 'whiteboard',
      ...(convId ? { conversation_id: convId } : {}),
    })
  }

  return {
    boards,
    loading: computed(() => artifactsStore.loading),
    refresh,
  }
}
