<script setup lang="ts">
/**
 * WhiteboardPageView — Full-page whiteboard editor.
 *
 * Layout: WhiteboardListSidebar (260px) | TldrawCanvas (flex)
 */
import { onMounted, computed, defineAsyncComponent } from 'vue'
import { useWhiteboardStore } from '../stores/whiteboard'
import WhiteboardListSidebar from '../components/whiteboard/WhiteboardListSidebar.vue'

const TldrawCanvas = defineAsyncComponent(
  () => import('../components/whiteboard/TldrawCanvas.vue')
)

const store = useWhiteboardStore()
const hasBoard = computed(() => store.currentBoard !== null)
const boardId = computed(() => store.currentBoard?.board_id ?? '')
const boardSnapshot = computed(() => store.currentBoard?.snapshot ?? null)

onMounted(() => {
  store.loadBoards()
})

async function onSelectBoard(id: string): Promise<void> {
  await store.loadBoard(id)
}

async function onDeleteBoard(id: string): Promise<void> {
  await store.deleteBoard(id)
}

function onSnapshotChange(snapshot: Record<string, unknown>): void {
  if (!store.currentBoard) return
  store.saveSnapshot(store.currentBoard.board_id, snapshot)
}
</script>

<template>
  <div class="whiteboard-page">
    <WhiteboardListSidebar
      @select="onSelectBoard"
      @delete="onDeleteBoard"
    />

    <div class="whiteboard-page__canvas">
      <template v-if="hasBoard">
        <TldrawCanvas
          :board-id="boardId"
          :snapshot="boardSnapshot"
          @change="onSnapshotChange"
        />
      </template>
      <template v-else>
        <div class="whiteboard-page__empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none"
            stroke="var(--text-muted)" stroke-width="1" stroke-linecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M3 9h18" />
            <path d="M9 3v18" />
          </svg>
          <p>Seleziona una lavagna o chiedi ad AL\CE di crearne una.</p>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.whiteboard-page {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: row;
  padding: 10px;
  gap: 10px;
  overflow: hidden;
  background: var(--surface-0);
  color: var(--text-primary);
  box-sizing: border-box;
}

.whiteboard-page__canvas {
  flex: 1;
  min-width: 0;
  display: flex;
  border-radius: var(--radius-lg, 12px);
  overflow: hidden;
  background: var(--surface-1);
  border: 1px solid var(--border);
}

.whiteboard-page__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.whiteboard-page__empty p {
  margin: 0;
}
</style>
