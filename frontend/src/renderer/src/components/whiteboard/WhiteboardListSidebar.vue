<script setup lang="ts">
/**
 * WhiteboardListSidebar — Left sidebar listing all saved whiteboards.
 *
 * Shows board title, shape count, and date.
 * Clicking a board emits 'select', the delete button emits 'delete'.
 */
import { computed } from 'vue'
import { useWhiteboardStore } from '../../stores/whiteboard'

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
      <li
        v-for="board in store.boards"
        :key="board.board_id"
        class="wb-sidebar__item"
        :class="{ 'wb-sidebar__item--active': board.board_id === activeBoardId }"
        @click="emit('select', board.board_id)"
      >
        <div class="wb-sidebar__item-top">
          <span class="wb-sidebar__item-title">{{ board.title }}</span>
          <button
            class="wb-sidebar__item-delete"
            title="Elimina lavagna"
            @click.stop="emit('delete', board.board_id)"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
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
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--border);
  overflow: hidden;
}

.wb-sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border);
}

.wb-sidebar__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.wb-sidebar__count {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--surface-3);
  padding: 1px 7px;
  border-radius: var(--radius-pill, 999px);
}

.wb-sidebar__loading,
.wb-sidebar__empty {
  padding: 24px 16px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

.wb-sidebar__list {
  list-style: none;
  margin: 0;
  padding: 6px;
  overflow-y: auto;
  flex: 1;
}

.wb-sidebar__item {
  padding: 10px 12px;
  border-radius: var(--radius-md, 8px);
  cursor: pointer;
  transition: background 150ms ease;
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
  gap: 8px;
}

.wb-sidebar__item-title {
  font-size: 13px;
  font-weight: 500;
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
  border-radius: var(--radius-sm, 4px);
  opacity: 0;
  transition: opacity 150ms ease, color 150ms ease;
}

.wb-sidebar__item:hover .wb-sidebar__item-delete {
  opacity: 1;
}

.wb-sidebar__item-delete:hover {
  color: var(--error, #ef4444);
}

.wb-sidebar__item-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
