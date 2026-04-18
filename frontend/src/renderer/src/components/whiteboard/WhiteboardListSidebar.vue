<script setup lang="ts">
/**
 * WhiteboardListSidebar — Left sidebar listing all saved whiteboards.
 *
 * Shows board title, shape count, and date.
 * Clicking a board emits 'select', the delete button emits 'delete'.
 */
import { computed } from 'vue'
import { useWhiteboardStore } from '../../stores/whiteboard'
import AppIcon from '../ui/AppIcon.vue'

const store = useWhiteboardStore()

const emit = defineEmits<{
  (e: 'select', boardId: string): void
  (e: 'delete', boardId: string): void
}>()

const activeBoardId = computed(() => store.currentBoard?.board_id ?? null)

/** Format a date string to a short readable format. */
function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86_400_000) {
    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' })
}
</script>

<template>
  <aside class="wb-sidebar">
    <div class="wb-sidebar__header">
      <h2 class="wb-sidebar__title">Lavagne</h2>
      <span class="wb-sidebar__count">{{ store.total }}</span>
    </div>

    <div v-if="store.loading" class="wb-sidebar__loading">Caricamento…</div>

    <div v-else-if="!store.hasBoards" class="wb-sidebar__empty">
      Nessuna lavagna. Chiedi ad AL\CE di creare una whiteboard!
    </div>

    <ul v-else class="wb-sidebar__list">
      <li v-for="board in store.boards" :key="board.board_id" class="wb-sidebar__item"
        :class="{ 'wb-sidebar__item--active': board.board_id === activeBoardId }"
        @click="emit('select', board.board_id)">
        <div class="wb-sidebar__item-top">
          <span class="wb-sidebar__item-title">{{ board.title }}</span>
          <button class="wb-sidebar__item-delete" title="Elimina lavagna" @click.stop="emit('delete', board.board_id)">
            <AppIcon name="x" :size="12" />
          </button>
        </div>
        <div v-if="board.conversation_title" class="wb-sidebar__item-conv">
          <AppIcon name="message" :size="10" />
          <span>{{ board.conversation_title }}</span>
        </div>
        <div class="wb-sidebar__item-meta">
          <span>{{ board.shape_count }} forme</span>
          <span>{{ formatDate(board.updated_at) }}</span>
        </div>
      </li>
    </ul>
  </aside>
</template>

<style scoped>
.wb-sidebar {
  width: 260px;
  min-width: 220px;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  overflow: hidden;
}

.wb-sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4) var(--space-2-5);
  border-bottom: 1px solid var(--border);
}

.wb-sidebar__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  margin: 0;
}

.wb-sidebar__count {
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: var(--surface-3);
  padding: 1px var(--space-2);
  border-radius: var(--radius-pill);
}

.wb-sidebar__loading,
.wb-sidebar__empty {
  padding: var(--space-6) var(--space-4);
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
}

.wb-sidebar__list {
  list-style: none;
  margin: 0;
  padding: var(--space-1-5);
  overflow-y: auto;
  flex: 1;
}

.wb-sidebar__item {
  padding: var(--space-2-5) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.wb-sidebar__item:hover {
  background: var(--surface-hover);
}

.wb-sidebar__item--active {
  background: var(--surface-selected);
  border: 1px solid var(--accent-border);
}

.wb-sidebar__item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.wb-sidebar__item-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.wb-sidebar__item-delete {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  border-radius: var(--radius-sm);
  opacity: 0;
  transition: opacity var(--transition-fast), color var(--transition-fast);
}

.wb-sidebar__item:hover .wb-sidebar__item-delete {
  opacity: 1;
}

.wb-sidebar__item-delete:hover {
  color: var(--danger);
}

.wb-sidebar__item-meta {
  display: flex;
  justify-content: space-between;
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.wb-sidebar__item-conv {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
