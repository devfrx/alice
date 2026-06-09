<script setup lang="ts">
/**
 * WhiteboardModule — Real adapter wrapping TldrawCanvas inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.boardId` — string UUID of the board to open. useArtifactAutoOpen
 *   supplies this key when auto-opening the tile for a freshly-created board.
 *
 * ## Multi-board handling
 * When a conversation contains several whiteboards, a {@link ModuleSelectorBar}
 * lets the user switch between them. Selection is resolved by
 * {@link useModuleItemSelection}: manual pick → `boardId` param → most-recent
 * board. The list comes from the whiteboard store (`store.boards`).
 *
 * ## Fallback
 * If nothing resolves yet, the store's `currentBoard` is used; only when no
 * board is available at all is a UiEmptyState rendered.
 *
 * ## Emits from TldrawCanvas
 * `change` (snapshot) — forwarded to the whiteboard store for persistence.
 */
import { computed, watch, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useWhiteboardStore } from '../../../stores/whiteboard'
import { useChatStore } from '../../../stores/chat'
import { useModuleItemSelection } from '../../../composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'
import type { WhiteboardListItem } from '../../../types/whiteboard'

const TldrawCanvas = defineAsyncComponent(() => import('../../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const store = useWhiteboardStore()
const chatStore = useChatStore()

const { currentId, select } = useModuleItemSelection<WhiteboardListItem>({
  items: () => store.boards,
  getId: (b) => b.board_id,
  preferredId: () => {
    const id = props.params?.boardId
    return typeof id === 'string' && id.length > 0 ? id : null
  },
})

/** Effective board id: resolved selection > param > store.currentBoard. */
const boardId = computed((): string | null => {
  if (currentId.value) return currentId.value
  const fromParams = props.params?.boardId
  if (typeof fromParams === 'string' && fromParams.length > 0) return fromParams
  if (store.currentBoard) return store.currentBoard.board_id
  return null
})

/** Snapshot: supplied by the store when the active board is already loaded. */
const snapshot = computed((): Record<string, unknown> | null => {
  if (store.currentBoard && boardId.value === store.currentBoard.board_id) {
    return store.currentBoard.snapshot ?? null
  }
  return null
})

/** One selector option per board in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  store.boards.map((b, i) => ({ value: b.board_id, label: b.title || `Lavagna ${i + 1}` })),
)

/** Persist snapshot changes via the store. */
function onSnapshotChange(snap: Record<string, unknown>): void {
  const id = boardId.value
  if (!id) return
  store.saveSnapshot(id, snap)
}

/**
 * Keep the board list scoped to the active conversation: reset stale boards
 * then reload boards for the current conversation whenever it changes.
 */
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    store.reset()
    if (id) void store.loadBoards(id)
  },
  { immediate: true },
)

/** If boardId changes to a value not yet in currentBoard, load its snapshot. */
watch(
  boardId,
  async (id) => {
    if (id && store.currentBoard?.board_id !== id) {
      await store.loadBoard(id)
    }
  },
  { immediate: false },
)
</script>

<template>
  <div class="whiteboard-module">
    <ModuleSelectorBar
      :model-value="currentId"
      :options="options"
      aria-label="Seleziona lavagna"
      @update:model-value="(v) => select(String(v))"
    />
    <TldrawCanvas
      v-if="boardId"
      :key="boardId"
      :board-id="boardId"
      :snapshot="snapshot"
      @change="onSnapshotChange"
    />
    <UiEmptyState
      v-else
      icon="edit"
      title="Nessuna lavagna"
      subtitle="Apri una lavagna dalla chat per visualizzarla qui."
    />
  </div>
</template>

<style scoped>
.whiteboard-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Let the canvas fill the height remaining under the selector bar. */
.whiteboard-module :deep(.tldraw-host) {
  flex: 1 1 0;
  min-height: 0;
}
</style>
