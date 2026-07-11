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
import { computed, nextTick, ref, onMounted, onBeforeUnmount } from 'vue'

import type { ConversationSummary } from '../../types/chat'
import AppIcon from '../ui/AppIcon.vue'
import { formatRelativeTime } from '../../utils/relativeTime'

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
  export: [id: string]
  'backup-all': []
}>()

// -----------------------------------------------------------------------
// Virtual scroll state
// -----------------------------------------------------------------------

/** Height of each conversation item in pixels.
 *  Each item renders at exactly 56 px (height: 56px in CSS, no top offset).
 *  Breakdown: padding-top (10px) + title line (≈15px) + gap (2px) + meta line (≈11px) + padding-bottom (10px) = 48px,
 *  but height is set explicitly to 56px so content is vertically centered with extra breathing room.
 *  left/right inset of 4px is purely visual (border-radius detached effect) and does not affect slot height.
 */
const ITEM_HEIGHT = 56
/** Extra items rendered above/below the visible area. */
const BUFFER = 5

const scrollContainer = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const containerHeight = ref(0)

const totalHeight = computed(() => props.conversations.length * ITEM_HEIGHT)

const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / ITEM_HEIGHT) - BUFFER))
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
/**
 * The inline rename input. Only one renders at a time (the row whose id
 * matches `renamingId`). A function ref is used because the input lives inside
 * a `v-for`, where a static string ref would be collected as an array.
 */
const renameInputRef = ref<HTMLInputElement | null>(null)

function setRenameInput(el: Element | null): void {
  renameInputRef.value = el as HTMLInputElement | null
}

function startRename(conv: ConversationSummary): void {
  renamingId.value = conv.id
  renameValue.value = conv.title ?? ''
  // `autofocus` is only honoured on initial page load, not for elements
  // inserted dynamically — focus + select explicitly once the input renders.
  nextTick(() => {
    renameInputRef.value?.focus()
    renameInputRef.value?.select()
  })
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

/** Human-readable "time ago" — delegates to the shared util. */
const timeAgo = (iso: string): string => formatRelativeTime(iso)
</script>

<template>
  <div class="conv-list">
    <!-- Section header: label + compact icon actions -->
    <div class="conv-list__header">
      <span class="conv-list__title">Conversazioni</span>
      <div class="conv-list__header-actions">
        <button
          class="conv-list__header-btn"
          aria-label="Nuova chat"
          title="Nuova chat"
          @click="emit('create')"
        >
          <AppIcon name="plus" :size="12" />
        </button>
        <button
          v-if="conversations.length > 0"
          class="conv-list__header-btn"
          aria-label="Backup di tutte le conversazioni"
          title="Backup di tutte le conversazioni"
          @click="emit('backup-all')"
        >
          <AppIcon name="folder" :size="11" />
        </button>
        <button
          v-if="conversations.length > 0"
          class="conv-list__header-btn conv-list__header-btn--danger"
          aria-label="Elimina tutte le conversazioni"
          title="Elimina tutte"
          @click="emit('delete-all')"
        >
          <AppIcon name="trash" :size="11" />
        </button>
      </div>
    </div>

    <!-- Virtual-scrolled conversation list -->
    <div
      ref="scrollContainer"
      class="conv-list__scroller"
      role="listbox"
      aria-label="Conversazioni"
      tabindex="0"
      @scroll="onScroll"
      @keydown="handleListKeydown"
    >
      <div class="conv-list__spacer" :style="{ height: totalHeight + 'px' }" role="presentation">
        <div
          v-for="{ conv, index, offset } in visibleItems"
          :key="conv.id"
          class="conv-item"
          :class="{
            'conv-item--active': conv.id === activeId,
            'conv-item--streaming': conv.id === streamingId,
            'conv-item--focused': index === focusedIndex
          }"
          role="option"
          :aria-selected="conv.id === activeId"
          :style="{ transform: `translateY(${offset}px)` }"
          @click="emit('select', conv.id)"
        >
          <!-- Normal display -->
          <template v-if="renamingId !== conv.id">
            <span class="conv-item__title">
              <span
                v-if="conv.id === streamingId"
                class="conv-item__streaming-dot"
                role="img"
                aria-label="Generazione in corso"
              />
              {{ conv.title ?? 'Nuova conversazione' }}
            </span>
            <div class="conv-item__meta">
              <span v-if="conv.message_count > 0" class="conv-item__count">{{
                conv.message_count
              }}</span>
              <span class="conv-item__time">{{ timeAgo(conv.updated_at) }}</span>
            </div>
          </template>

          <!-- Inline rename -->
          <template v-else>
            <input
              :ref="(el) => setRenameInput(el as Element | null)"
              v-model="renameValue"
              class="conv-item__rename-input"
              aria-label="Rinomina conversazione"
              @keydown.enter.stop="confirmRename(conv.id)"
              @keydown.escape.stop="cancelRename"
              @click.stop
            />
          </template>

          <!-- Action buttons (slide-in on hover) -->
          <div class="conv-item__actions" @click.stop>
            <button
              v-if="renamingId !== conv.id"
              class="conv-item__action"
              aria-label="Esporta conversazione"
              title="Esporta backup JSON"
              @click="emit('export', conv.id)"
            >
              <AppIcon name="folder" :size="11" />
            </button>
            <button
              v-if="renamingId !== conv.id"
              class="conv-item__action"
              aria-label="Rinomina conversazione"
              title="Rinomina"
              @click="startRename(conv)"
            >
              <AppIcon name="pencil" :size="11" />
            </button>
            <button
              v-if="renamingId === conv.id"
              class="conv-item__action conv-item__action--confirm"
              aria-label="Conferma"
              title="Conferma"
              @click="confirmRename(conv.id)"
            >
              <AppIcon name="check" :size="11" :stroke-width="2.5" />
            </button>
            <button
              class="conv-item__action conv-item__action--danger"
              aria-label="Elimina conversazione"
              title="Elimina"
              :disabled="conv.id === streamingId"
              @click="emit('delete', conv.id)"
            >
              <AppIcon name="trash" :size="11" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="conversations.length === 0" class="conv-list__empty">
      <span class="conv-list__empty-icon" aria-hidden="true">
        <AppIcon name="message" :size="28" :stroke-width="1.2" />
      </span>
      <span class="conv-list__empty-text">Nessuna conversazione</span>
      <span class="conv-list__empty-sub">Crea una nuova chat per iniziare</span>
    </div>
  </div>
</template>

<style scoped>
/* ─── ConversationList — Claude-style compact sidebar list ─── */

/* Root */
.conv-list {
  display: flex;
  flex-direction: column;
  padding: 0 var(--space-1-5) var(--space-2);
  flex: 1;
  min-height: 0;
  position: relative;
}

/* ─── Section header ────────────────────────────────────────── */
.conv-list__header {
  display: flex;
  align-items: center;
  padding: var(--space-2) var(--space-2) var(--space-1-5);
  margin-top: var(--space-1);
  flex-shrink: 0;
}

/* Uppercase muted label with generous letter-spacing — Claude section header style */
.conv-list__title {
  flex: 1;
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.conv-list__header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-0-5);
}

/* Compact icon button — subtle, accent on hover */
.conv-list__header-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.conv-list__header-btn:hover {
  background: var(--surface-hover);
  color: var(--accent);
}

.conv-list__header-btn--danger:hover {
  color: var(--danger);
  background: var(--danger-hover);
}

/* ─── Scroller ──────────────────────────────────────────────── */
.conv-list__scroller {
  flex: 1;
  overflow-y: auto;
  position: relative;
  outline: none;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-3) transparent;
}

.conv-list__scroller::-webkit-scrollbar {
  width: 3px;
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
  border-radius: var(--radius-sm);
}

.conv-list__spacer {
  position: relative;
  width: 100%;
}

/* ─── Conversation item ─────────────────────────────────────── */
/*
 * ITEM_HEIGHT = 56px (matches the constant in <script>).
 * Item is exactly 56px tall (height: 56px). No top offset — item fills its slot cleanly.
 * Padding: 10px top + 10px bottom gives comfortable breathing room.
 * left/right inset of 4px creates the detached floating-row look without affecting slot height.
 * The virtual-scroll spacer is n*56px; slots and items are in perfect alignment.
 */
.conv-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 10px var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  position: absolute;
  left: 4px;
  right: 4px;
  top: 0;
  height: 56px;
  transition:
    background var(--transition-fast),
    box-shadow var(--transition-fast);
}

.conv-item:hover {
  background: var(--surface-hover);
}

/*
 * Active: --surface-selected background is the sole selection cue (no accent bar).
 */
.conv-item--active {
  background: var(--surface-selected);
}

.conv-item--active:hover {
  background: var(--surface-selected);
}

/* Streaming — same base as active; the pulsing dot indicates progress */
.conv-item--streaming {
  background: var(--surface-selected);
}

/* Keyboard-focused item */
.conv-item--focused {
  outline: none;
  background: var(--surface-hover);
}

.conv-item--focused.conv-item--active {
  background: var(--surface-selected);
}

/* ─── Title ─────────────────────────────────────────────────── */
.conv-item__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 54px;
  line-height: 1.3;
}

/* Active/selected: title becomes primary text color */
.conv-item--active .conv-item__title,
.conv-item--streaming .conv-item__title {
  color: var(--text-primary);
}

/* ─── Meta row ──────────────────────────────────────────────── */
.conv-item__meta {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  margin-top: 2px;
  padding-right: 54px;
}

.conv-item__count {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0.6;
  font-variant-numeric: tabular-nums;
}

.conv-item__time {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  margin-left: auto;
  opacity: 0.65;
}

.conv-item--active .conv-item__count,
.conv-item--active .conv-item__time {
  opacity: 0.9;
}

/* ─── Streaming dot ─────────────────────────────────────────── */
/* Small pulsing accent dot — subtle indicator of in-progress generation */
.conv-item__streaming-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: var(--accent);
  margin-right: var(--space-1);
  vertical-align: middle;
  flex-shrink: 0;
  animation: streaming-pulse 1.4s ease-in-out infinite;
}

@keyframes streaming-pulse {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.3;
  }
}

/* ─── Rename input ──────────────────────────────────────────── */
/* Tokenized clean field: subtle border, radius-sm, accent focus ring */
.conv-item__rename-input {
  width: 100%;
  padding: var(--space-1) var(--space-1-5);
  background: var(--surface-1);
  border: 1px solid var(--border-hover);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  outline: none;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.conv-item__rename-input:focus {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-dim);
}

/* ─── Action buttons ────────────────────────────────────────── */
/* Compact icon tray — appears on row hover/focus; subtle glass background */
.conv-item__actions {
  position: absolute;
  top: 50%;
  right: var(--space-1-5);
  transform: translateY(-50%);
  display: flex;
  gap: 1px;
  opacity: 0;
  pointer-events: none;
  background: var(--surface-2);
  padding: 2px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  transition: opacity var(--transition-fast);
}

.conv-item:hover .conv-item__actions,
.conv-item--focused .conv-item__actions {
  opacity: 1;
  pointer-events: auto;
}

/* Icon button: --text-muted default → --text-primary on hover */
.conv-item__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
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

.conv-item__action--confirm:hover {
  color: var(--success);
}

/* Delete → danger color on hover */
.conv-item__action--danger:hover {
  color: var(--danger);
  background: var(--danger-hover);
}

/* ─── Empty state ───────────────────────────────────────────── */
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
  opacity: 0.35;
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

/* ─── Reduced motion ────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .conv-item,
  .conv-item__actions,
  .conv-item__rename-input,
  .conv-list__header-btn,
  .conv-item__action,
  .conv-item__streaming-dot {
    transition: none;
    animation: none;
  }
}
</style>
