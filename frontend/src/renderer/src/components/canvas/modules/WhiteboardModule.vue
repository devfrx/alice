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
 * board. The list derives from the unified artifacts store via
 * {@link useWhiteboardBoards}.
 *
 * ## Emits from TldrawCanvas
 * `change` (snapshot) — persisted via the unified artifacts store.
 */
import { computed, ref, watch, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useArtifactsStore } from '../../../stores/artifacts'
import { useChatStore } from '../../../stores/chat'
import {
  useWhiteboardBoards,
  type WhiteboardBoardItem,
} from '../../../composables/whiteboard/useWhiteboardBoards'
import { useModuleItemSelection } from '../../../composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'

const TldrawCanvas = defineAsyncComponent(() => import('../../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const artifactsStore = useArtifactsStore()
const chatStore = useChatStore()
const { boards, refresh } = useWhiteboardBoards(
  () => chatStore.currentConversation?.id ?? null,
)

const { currentId, select } = useModuleItemSelection<WhiteboardBoardItem>({
  items: () => boards.value,
  getId: (b) => b.boardId,
  preferredId: () => {
    const id = props.params?.boardId
    return typeof id === 'string' && id.length > 0 ? id : null
  },
})

/** Effective board id: resolved selection > param. */
const boardId = computed((): string | null => {
  if (currentId.value) return currentId.value
  const fromParams = props.params?.boardId
  if (typeof fromParams === 'string' && fromParams.length > 0) return fromParams
  return null
})

/** tldraw snapshot of the active board (from the artifact JSON content). */
const snapshot = ref<Record<string, unknown> | null>(null)

watch(
  boardId,
  async (id) => {
    snapshot.value = null
    if (!id) return
    const content = await artifactsStore.fetchContent(id)
    const snap = content?.snapshot
    snapshot.value = snap && typeof snap === 'object' ? (snap as Record<string, unknown>) : null
  },
  { immediate: true },
)

/** Persist snapshot changes via the unified store (top-level merge). */
function onSnapshotChange(snap: Record<string, unknown>): void {
  const id = boardId.value
  if (!id) return
  void artifactsStore.saveContent(id, { snapshot: snap })
}

/** One selector option per board in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  boards.value.map((b, i) => ({ value: b.boardId, label: b.title || `Lavagna ${i + 1}` })),
)

/** Reload the board list when the active conversation changes. */
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    if (id) void refresh()
  },
  { immediate: true },
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
