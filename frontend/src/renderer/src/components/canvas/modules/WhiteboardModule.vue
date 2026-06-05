<script setup lang="ts">
/**
 * WhiteboardModule — Real adapter wrapping TldrawCanvas inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.boardId` — string UUID of the board to open.
 *   TldrawCanvas requires this prop (it is `required: true`) and fetches the
 *   snapshot from the backend when none is supplied.
 *   T10 (useArtifactAutoOpen) must supply this key when opening the tile.
 *
 * ## Fallback
 * If `params.boardId` is absent, the adapter tries to use the most-recently
 * selected board from the whiteboard store (`store.currentBoard`), then the
 * first board in `store.boards` (loading the list if needed).  If after that
 * no board is available, a UiEmptyState is rendered.
 *
 * ## Emits from TldrawCanvas
 * `change` (snapshot) — forwarded to the whiteboard store for persistence.
 */
import { computed, watch, onMounted, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useWhiteboardStore } from '../../../stores/whiteboard'

const TldrawCanvas = defineAsyncComponent(() => import('../../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const store = useWhiteboardStore()

/** Resolved board ID: params > currentBoard > first board in list. */
const boardId = computed((): string | null => {
  // 1. Explicit param from T10 / tile params
  const fromParams = props.params?.boardId
  if (typeof fromParams === 'string' && fromParams.length > 0) return fromParams

  // 2. Board already open in the whiteboard store
  if (store.currentBoard) return store.currentBoard.board_id

  // 3. First board in the loaded list
  if (store.boards.length > 0) return store.boards[0].board_id

  return null
})

/** Snapshot: supplied by the store if the board is already loaded there. */
const snapshot = computed((): Record<string, unknown> | null => {
  if (store.currentBoard && boardId.value === store.currentBoard.board_id) {
    return store.currentBoard.snapshot ?? null
  }
  return null
})

/** Persist snapshot changes via the store. */
function onSnapshotChange(snap: Record<string, unknown>): void {
  const id = boardId.value
  if (!id) return
  store.saveSnapshot(id, snap)
}

/** Ensure the board list is loaded so the fallback can pick the first board. */
onMounted(async () => {
  if (!store.hasBoards && store.boards.length === 0 && !store.loading) {
    await store.loadBoards()
  }
})

/** If boardId changes to a value not yet in currentBoard, load it. */
watch(
  boardId,
  async (id) => {
    if (id && store.currentBoard?.board_id !== id) {
      await store.loadBoard(id)
    }
  },
  { immediate: false }
)
</script>

<template>
  <div class="whiteboard-module">
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
  overflow: hidden;
}
</style>
