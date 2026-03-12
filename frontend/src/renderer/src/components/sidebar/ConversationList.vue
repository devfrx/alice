<script setup lang="ts">
/**
 * ConversationList.vue — Virtualised list of conversation summaries.
 *
 * Features:
 * - "New Conversation" button at the top.
 * - Virtual scrolling for 1000+ conversations.
 * - Keyboard navigation (arrow keys, Enter, Escape).
 * - ARIA roles for accessibility.
 */
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'

import type { ConversationSummary } from '../../types/chat'

const props = defineProps<{
  /** Conversation summaries to display. */
  conversations: ConversationSummary[]
  /** ID of the currently active conversation (null = none). */
  activeId: string | null
  /** ID of the conversation currently being streamed (null = none). */
  streamingId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  create: []
  delete: [id: string]
  'delete-all': []
  rename: [id: string, title: string]
  'open-file': [id: string]
}>()

// -----------------------------------------------------------------------
// Virtual scroll state
// -----------------------------------------------------------------------

/** Height of each conversation item in pixels. */
const ITEM_HEIGHT = 52
/** Extra items rendered above/below the visible area. */
const BUFFER = 5

const scrollContainer = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const containerHeight = ref(0)

const totalHeight = computed(() => props.conversations.length * ITEM_HEIGHT)

const startIndex = computed(() =>
  Math.max(0, Math.floor(scrollTop.value / ITEM_HEIGHT) - BUFFER)
)
const endIndex = computed(() =>
  Math.min(
    props.conversations.length,
    Math.ceil((scrollTop.value + containerHeight.value) / ITEM_HEIGHT) + BUFFER
  )
)

const visibleItems = computed(() =>
  props.conversations.slice(startIndex.value, endIndex.value).map((conv, i) => ({
    conv,
    index: startIndex.value + i,
    offset: (startIndex.value + i) * ITEM_HEIGHT
  }))
)

function onScroll(): void {
  if (scrollContainer.value) {
    scrollTop.value = scrollContainer.value.scrollTop
  }
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (scrollContainer.value) {
    containerHeight.value = scrollContainer.value.clientHeight
    resizeObserver = new ResizeObserver(([entry]) => {
      containerHeight.value = entry.contentRect.height
    })
    resizeObserver.observe(scrollContainer.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

// -----------------------------------------------------------------------
// Inline rename
// -----------------------------------------------------------------------

/** ID of the conversation currently being renamed (inline edit). */
const renamingId = ref<string | null>(null)
/** Temporary value while the user edits the title. */
const renameValue = ref('')

function startRename(conv: ConversationSummary): void {
  renamingId.value = conv.id
  renameValue.value = conv.title ?? ''
}

function confirmRename(id: string): void {
  const trimmed = renameValue.value.trim()
  if (trimmed) emit('rename', id, trimmed)
  renamingId.value = null
}

function cancelRename(): void {
  renamingId.value = null
}

// -----------------------------------------------------------------------
// Keyboard navigation (Item 7)
// -----------------------------------------------------------------------

/** Index of the currently focused conversation (-1 = none). */
const focusedIndex = ref(-1)

function handleListKeydown(event: KeyboardEvent): void {
  const len = props.conversations.length
  if (len === 0) return

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      focusedIndex.value = Math.min(focusedIndex.value + 1, len - 1)
      scrollToIndex(focusedIndex.value)
      break
    case 'ArrowUp':
      event.preventDefault()
      focusedIndex.value = Math.max(focusedIndex.value - 1, 0)
      scrollToIndex(focusedIndex.value)
      break
    case 'Enter':
      event.preventDefault()
      if (focusedIndex.value >= 0 && focusedIndex.value < len) {
        emit('select', props.conversations[focusedIndex.value].id)
      }
      break
    case 'Home':
      event.preventDefault()
      focusedIndex.value = 0
      scrollToIndex(0)
      break
    case 'End':
      event.preventDefault()
      focusedIndex.value = len - 1
      scrollToIndex(len - 1)
      break
  }
}

function scrollToIndex(index: number): void {
  if (!scrollContainer.value) return
  const itemTop = index * ITEM_HEIGHT
  const itemBottom = itemTop + ITEM_HEIGHT
  const viewTop = scrollContainer.value.scrollTop
  const viewBottom = viewTop + containerHeight.value
  if (itemTop < viewTop) {
    scrollContainer.value.scrollTop = itemTop
  } else if (itemBottom > viewBottom) {
    scrollContainer.value.scrollTop = itemBottom - containerHeight.value
  }
}

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

/**
 * Compute a human-readable "time ago" string from an ISO timestamp.
 */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'adesso'
  if (mins < 60) return `${mins} min fa`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h fa`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'ieri'
  if (days < 30) return `${days}g fa`
  return new Date(iso).toLocaleDateString()
}
</script>

<template>
  <div class="conv-list">
    <!-- New conversation — prominent button with circle-plus badge -->
    <button class="conv-list__new" aria-label="Nuova chat" @click="emit('create')">
      <span class="conv-list__new-icon" aria-hidden="true">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </span>
      <span class="conv-list__new-label">Nuova chat</span>
    </button>

    <!-- Delete all — minimal text-link style -->
    <button v-if="conversations.length > 0" class="conv-list__delete-all" aria-label="Elimina tutte le conversazioni"
      @click="emit('delete-all')">
      Elimina tutte
    </button>

    <!-- Virtual-scrolled conversation list -->
    <div ref="scrollContainer" class="conv-list__scroller" role="listbox" aria-label="Conversazioni" tabindex="0"
      @scroll="onScroll" @keydown="handleListKeydown">
      <div class="conv-list__spacer" :style="{ height: totalHeight + 'px' }" role="presentation">
        <div v-for="{ conv, index, offset } in visibleItems" :key="conv.id" class="conv-item" :class="{
          'conv-item--active': conv.id === activeId,
          'conv-item--streaming': conv.id === streamingId,
          'conv-item--focused': index === focusedIndex
        }" role="option" :aria-selected="conv.id === activeId" :style="{ transform: `translateY(${offset}px)` }"
          @click="emit('select', conv.id)">
          <!-- Left accent bar (always present, styled per state) -->
          <span class="conv-item__bar" aria-hidden="true" />

          <!-- Normal display -->
          <template v-if="renamingId !== conv.id">
            <span class="conv-item__title">
              <span v-if="conv.id === streamingId" class="conv-item__streaming-dot" role="img"
                aria-label="Generazione in corso" />
              {{ conv.title ?? 'Nuova conversazione' }}
            </span>
            <span class="conv-item__meta">
              <span class="conv-item__meta-badge">
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                  aria-hidden="true">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <span>{{ conv.message_count }}</span>
              </span>
              <span class="conv-item__time">{{ timeAgo(conv.updated_at) }}</span>
            </span>
          </template>

          <!-- Inline rename -->
          <template v-else>
            <input v-model="renameValue" class="conv-item__rename-input" autofocus aria-label="Rinomina conversazione"
              @keydown.enter.stop="confirmRename(conv.id)" @keydown.escape.stop="cancelRename" @click.stop />
          </template>

          <!-- Action buttons (slide-in on hover) -->
          <div class="conv-item__actions" @click.stop>
            <button v-if="renamingId !== conv.id" class="conv-item__action" aria-label="Apri cartella"
              title="Apri nel file manager" @click="emit('open-file', conv.id)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
            </button>
            <button v-if="renamingId !== conv.id" class="conv-item__action" aria-label="Rinomina conversazione"
              title="Rinomina" @click="startRename(conv)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
              </svg>
            </button>
            <button v-if="renamingId === conv.id" class="conv-item__action conv-item__action--confirm"
              aria-label="Conferma" title="Conferma" @click="confirmRename(conv.id)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </button>
            <button class="conv-item__action conv-item__action--danger" aria-label="Elimina conversazione"
              title="Elimina" :disabled="conv.id === streamingId" @click="emit('delete', conv.id)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14H6L5 6" />
                <path d="M10 11v6" />
                <path d="M14 11v6" />
                <path d="M9 6V4h6v2" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state with staggered fade-in -->
    <div v-if="conversations.length === 0" class="conv-list__empty">
      <span class="conv-list__empty-icon" aria-hidden="true">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </span>
      <span class="conv-list__empty-text">Nessuna conversazione</span>
      <span class="conv-list__empty-sub">Crea una nuova chat per iniziare</span>
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   ConversationList — Supabase-style ultra-flat design
   ═══════════════════════════════════════════════════════════ */

/* ------------------------------------------------- Root */
.conv-list {
  display: flex;
  flex-direction: column;
  padding: var(--space-1) var(--space-2) var(--space-2);
  flex: 1;
  min-height: 0;
  position: relative;
}

/* ------------------------------------------------- New chat button */
.conv-list__new {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-2-5);
  margin-bottom: var(--space-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  flex-shrink: 0;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.conv-list__new-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: color var(--transition-fast);
}

.conv-list__new-label {
  flex: 1;
}

.conv-list__new:hover {
  background: var(--surface-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.conv-list__new:hover .conv-list__new-icon {
  color: var(--text-primary);
}

.conv-list__new:focus-visible {
  box-shadow: var(--focus-ring-shadow);
  outline: none;
}

/* ------------------------------------------------- Delete all */
.conv-list__delete-all {
  align-self: flex-end;
  display: flex;
  align-items: center;
  padding: var(--space-0-5) var(--space-1);
  margin-bottom: var(--space-1);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: var(--weight-regular);
  cursor: pointer;
  flex-shrink: 0;
  transition:
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.conv-list__delete-all:hover {
  color: var(--danger);
}

.conv-list__delete-all:focus-visible {
  box-shadow: var(--focus-ring-shadow);
  outline: none;
  border-radius: var(--radius-xs);
}

/* ------------------------------------------------- Scroller */
.conv-list__scroller {
  flex: 1;
  overflow-y: auto;
  position: relative;
  outline: none;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-3) transparent;
}

.conv-list__scroller::-webkit-scrollbar {
  width: 4px;
}

.conv-list__scroller::-webkit-scrollbar-track {
  background: transparent;
}

.conv-list__scroller::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: var(--radius-xs);
}

.conv-list__scroller::-webkit-scrollbar-thumb:hover {
  background: var(--surface-4);
}

.conv-list__scroller:focus-visible {
  box-shadow: var(--focus-ring-shadow);
  border-radius: var(--radius-sm);
}

.conv-list__spacer {
  position: relative;
  width: 100%;
}

/* ------------------------------------------------- Conversation item */
.conv-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-sm);
  cursor: pointer;
  position: absolute;
  left: 0;
  right: 0;
  height: 52px;
  transition: background var(--transition-fast);
}

/* Accent bar — hidden in Supabase style */
.conv-item__bar {
  display: none;
}

.conv-item:hover {
  background: var(--surface-hover);
}

/* Active state — stronger bg fill, no bar */
.conv-item--active {
  background: var(--surface-active);
}

.conv-item--active:hover {
  background: var(--surface-active);
}

/* Streaming — same as active */
.conv-item--streaming {
  background: var(--surface-active);
}

/* Keyboard-focused item */
.conv-item--focused {
  box-shadow: var(--focus-ring-shadow);
}

/* ------------------------------------------------- Title */
.conv-item__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 52px;
  line-height: 1.35;
}

.conv-item--active .conv-item__title {
  color: var(--text-primary);
}

/* ------------------------------------------------- Metadata row */
.conv-item__meta {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: var(--leading-tight);
  padding-right: 52px;
}

.conv-item--active .conv-item__meta {
  color: var(--text-secondary);
}

.conv-item__meta-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  opacity: 0.7;
}

.conv-item__time {
  margin-left: auto;
}

/* ------------------------------------------------- Streaming dot */
.conv-item__streaming-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: var(--accent);
  margin-right: var(--space-1);
  vertical-align: middle;
  flex-shrink: 0;
  opacity: 1;
}

/* ------------------------------------------------- Rename input */
.conv-item__rename-input {
  width: 100%;
  padding: var(--space-1) var(--space-1-5);
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  outline: none;
  transition: border-color var(--transition-fast);
}

.conv-item__rename-input:focus {
  border-color: var(--accent);
}

/* ------------------------------------------------- Action buttons */
.conv-item__actions {
  position: absolute;
  top: 50%;
  right: var(--space-1);
  transform: translateY(-50%);
  display: flex;
  gap: 2px;
  opacity: 0;
  pointer-events: none;
  background: var(--surface-1);
  padding: var(--space-0-5);
  border-radius: var(--radius-sm);
  transition: opacity var(--transition-fast);
}

.conv-item:hover .conv-item__actions,
.conv-item--focused .conv-item__actions {
  opacity: 1;
  pointer-events: auto;
}

.conv-item__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.conv-item__action:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.conv-item__action:focus-visible {
  box-shadow: var(--focus-ring-shadow);
  outline: none;
}

.conv-item__action--confirm:hover {
  color: var(--success);
}

.conv-item__action--danger:hover {
  color: var(--danger);
}

/* ------------------------------------------------- Empty state */
.conv-list__empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-4);
  pointer-events: none;
}

.conv-list__empty-icon {
  color: var(--text-muted);
  opacity: 0.5;
}

.conv-list__empty-text {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
}

.conv-list__empty-sub {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* ------------------------------------------------- Reduced motion */
@media (prefers-reduced-motion: reduce) {

  .conv-item,
  .conv-item__actions,
  .conv-item__rename-input,
  .conv-list__new,
  .conv-list__new-icon,
  .conv-list__delete-all,
  .conv-item__action {
    transition: none;
  }
}
</style>