<script setup lang="ts">
/**
 * WhiteboardPageView — Full-page whiteboard editor.
 *
 * Layout: WhiteboardListSidebar (260px) | TldrawCanvas (flex)
 */
import { onMounted, ref, computed, defineAsyncComponent } from 'vue'
import { useArtifactsStore } from '../stores/artifacts'
import { useWhiteboardBoards } from '../composables/whiteboard/useWhiteboardBoards'
import WhiteboardListSidebar from '../components/whiteboard/WhiteboardListSidebar.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const TldrawCanvas = defineAsyncComponent(
  () => import('../components/whiteboard/TldrawCanvas.vue')
)

const artifactsStore = useArtifactsStore()
const { boards, loading, refresh } = useWhiteboardBoards()

const currentBoardId = ref<string | null>(null)
const currentSnapshot = ref<Record<string, unknown> | null>(null)
const hasBoard = computed(() => currentBoardId.value !== null)

onMounted(() => {
  void refresh()
})

async function onSelectBoard(id: string): Promise<void> {
  currentBoardId.value = id
  currentSnapshot.value = null
  const content = await artifactsStore.fetchContent(id, true)
  if (currentBoardId.value !== id) return // a newer selection won — drop this resolution
  const snap = content?.snapshot
  currentSnapshot.value = snap && typeof snap === 'object' ? (snap as Record<string, unknown>) : null
}

async function onDeleteBoard(id: string): Promise<void> {
  await artifactsStore.remove(id, true)
  if (currentBoardId.value === id) {
    currentBoardId.value = null
    currentSnapshot.value = null
  }
}

function onSnapshotChange(snapshot: Record<string, unknown>): void {
  if (!currentBoardId.value) return
  void artifactsStore.saveContent(currentBoardId.value, { snapshot })
}
</script>

<template>
  <div class="whiteboard-page" aria-label="Lavagna">
    <WhiteboardListSidebar
      :boards="boards"
      :active-board-id="currentBoardId"
      :loading="loading"
      @select="onSelectBoard"
      @delete="onDeleteBoard"
    />

    <div class="whiteboard-page__canvas">
      <template v-if="hasBoard">
        <TldrawCanvas :board-id="currentBoardId ?? ''" :snapshot="currentSnapshot" @change="onSnapshotChange" />
      </template>
      <template v-else>
        <div class="whiteboard-page__empty">
          <AppIcon name="whiteboard-card" :size="48" :stroke-width="1" />
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
  padding: var(--space-2-5);
  gap: var(--space-2-5);
  overflow: hidden;
  background: var(--surface-0);
  color: var(--text-primary);
  box-sizing: border-box;
}

.whiteboard-page__canvas {
  flex: 1;
  min-width: 0;
  display: flex;
  border-radius: var(--radius-lg);
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
  gap: var(--space-3);
  color: var(--text-muted);
  font-size: var(--text-base);
}

.whiteboard-page__empty p {
  margin: 0;
}
</style>
