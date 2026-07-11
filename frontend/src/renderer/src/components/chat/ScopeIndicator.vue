<script setup lang="ts">
/**
 * ScopeIndicator — compact input-bar chip + inline management popover for a
 * conversation's workspace scope.
 *
 * The *scope* is the set of filesystem folders the agent's filesystem/terminal
 * tools are confined to. It is the sole, in-composer surface for scope: the chip
 * shows the current scope at a glance (basename + count, amber when empty), and
 * clicking it opens a popover to add (native directory picker), remove, or clear
 * folders without leaving the chat.
 *
 * ## Data flow
 * On mount and whenever `conversationId` changes, the scope is fetched once via
 * {@link useScopeStore.ensureForConversation}. Live updates arrive out-of-band
 * through the `scope.updated` events-WS frame (folded by the scope store), so no
 * polling is needed here.
 *
 * ## Idle guard (mirrors ScopeManager)
 * The backend only accepts scope mutations while the conversation is idle. The
 * UI mirrors this two ways:
 * - Add / remove / clear are disabled while the current conversation is
 *   streaming ({@link useChatStore.isStreamingCurrentConversation}), with a hint.
 * - As a backstop (a turn may start while the native picker is open), a `PUT` /
 *   `DELETE` rejected with {@link ApiError} `status === 409` ("scope_locked") is
 *   caught and surfaced as a transient inline message (~5s auto-clear).
 *
 * Mounted in the Horizon cockpit ({@link HorizonCockpit}) next to the composer.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import UiPopover from '../ui/UiPopover.vue'
import { useChatStore } from '../../stores/chat'
import { useScopeStore } from '../../stores/scope'
import { ApiError } from '../../services/api'
import { scopeChipLabel, scopeTooltip } from './scopeIndicatorLabel'

const props = defineProps<{
  /** Conversation whose scope this chip reflects/edits (null when none open). */
  conversationId: string | null
}>()

const BUSY_HINT = 'Scope modificabile a generazione ferma.'
const LOCKED_MSG = 'Scope bloccato: una generazione è in corso.'
const GENERIC_ERR = 'Impossibile aggiornare lo scope. Riprova.'

const chatStore = useChatStore()
const scopeStore = useScopeStore()

/** Scope folders for the subject conversation (empty when none). */
const folders = computed<string[]>(() =>
  props.conversationId ? scopeStore.foldersFor(props.conversationId) : []
)

/** Compact chip label + empty flag (amber styling when empty). */
const label = computed(() => scopeChipLabel(folders.value))
/** Full-path tooltip for the chip. */
const tooltip = computed(() => scopeTooltip(folders.value))

/** True while the current conversation is streaming — gates mutations. */
const busy = computed<boolean>(() => chatStore.isStreamingCurrentConversation)
/** Whether scope mutations are currently allowed in the UI. */
const canEdit = computed<boolean>(() => props.conversationId !== null && !busy.value)

const isOpen = ref(false)
/** Trigger chip — anchor for the teleported popover. */
const triggerRef = ref<HTMLElement | null>(null)

/** Last error message to surface inline (auto-dismissed). */
const error = ref<string | null>(null)
let errorTimer: ReturnType<typeof setTimeout> | null = null

function clearError(): void {
  error.value = null
  if (errorTimer) {
    clearTimeout(errorTimer)
    errorTimer = null
  }
}

/** Show a transient inline error that clears itself after a few seconds. */
function flashError(message: string): void {
  error.value = message
  if (errorTimer) clearTimeout(errorTimer)
  errorTimer = setTimeout(() => {
    error.value = null
    errorTimer = null
  }, 5000)
}

/** Fetch-once the scope for a given conversation id and reset any stale error. */
function load(id: string | null): void {
  clearError()
  if (id) void scopeStore.ensureForConversation(id)
}

onMounted(() => load(props.conversationId))
watch(
  () => props.conversationId,
  (id) => {
    isOpen.value = false
    load(id)
  }
)
onBeforeUnmount(() => {
  if (errorTimer) clearTimeout(errorTimer)
})

function toggleOpen(): void {
  if (props.conversationId === null) return
  isOpen.value = !isOpen.value
}

/**
 * Run a scope mutation, mapping a 409 conflict (turn running) to the
 * "scope locked" message and any other failure to a generic one.
 */
async function mutate(op: () => Promise<void>): Promise<void> {
  clearError()
  try {
    await op()
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      flashError(LOCKED_MSG)
    } else {
      flashError(GENERIC_ERR)
    }
  }
}

/** Pick a folder via the native dialog and add it to the scope (deduped). */
async function addFolder(): Promise<void> {
  const id = props.conversationId
  if (!id || !canEdit.value) return
  const dir = await window.electron.fileOps.selectDirectory()
  if (!dir) return
  if (folders.value.includes(dir)) return // already in scope — skip
  await mutate(() => scopeStore.setFolders(id, [...folders.value, dir]))
}

/** Remove a single folder from the scope. */
async function removeFolder(target: string): Promise<void> {
  const id = props.conversationId
  if (!id || !canEdit.value) return
  await mutate(() =>
    scopeStore.setFolders(
      id,
      folders.value.filter((f) => f !== target)
    )
  )
}

/** Clear all folders from the scope. */
async function clearAll(): Promise<void> {
  const id = props.conversationId
  if (!id || !canEdit.value) return
  await mutate(() => scopeStore.clear(id))
}

/** Last path segment, used as the friendlier primary label for a folder. */
function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] ?? path
}
</script>

<template>
  <div class="scope-ind">
    <button
      ref="triggerRef"
      type="button"
      class="scope-ind__chip"
      :class="{ 'scope-ind__chip--open': isOpen, 'scope-ind__chip--empty': label.empty }"
      :disabled="conversationId === null"
      :title="tooltip"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggleOpen"
    >
      <AppIcon name="folder" :size="12" />
      <span class="scope-ind__chip-label">{{ label.text }}</span>
    </button>

    <UiPopover
      :open="isOpen"
      :anchor-el="triggerRef"
      placement="top"
      align="start"
      width="300px"
      aria-label="Scope cartelle"
      panel-class="scope-ind__pop"
      @update:open="isOpen = $event"
    >
      <div class="scope-ind__pop-head">
        <span class="scope-ind__pop-title">Scope cartelle</span>
        <button
          v-if="folders.length > 0"
          type="button"
          class="scope-ind__clear"
          :disabled="!canEdit"
          :title="busy ? BUSY_HINT : 'Rimuovi tutte le cartelle'"
          @click="clearAll"
        >
          Svuota
        </button>
      </div>

      <p v-if="busy" class="scope-ind__hint" role="status">
        <AppIcon name="lightning" :size="12" aria-hidden="true" />
        <span>{{ BUSY_HINT }}</span>
      </p>

      <p v-if="error" class="scope-ind__error" role="alert">
        <AppIcon name="alert-triangle" :size="12" aria-hidden="true" />
        <span>{{ error }}</span>
      </p>

      <ul v-if="folders.length > 0" class="scope-ind__list" role="list">
        <li v-for="folder in folders" :key="folder" class="scope-ind__item">
          <AppIcon name="folder" :size="13" class="scope-ind__item-icon" aria-hidden="true" />
          <span class="scope-ind__item-text">
            <span class="scope-ind__item-name">{{ folderName(folder) }}</span>
            <span class="scope-ind__item-path" :title="folder">{{ folder }}</span>
          </span>
          <button
            type="button"
            class="scope-ind__remove"
            :disabled="!canEdit"
            :title="busy ? BUSY_HINT : 'Rimuovi dallo scope'"
            :aria-label="`Rimuovi ${folder} dallo scope`"
            @click="removeFolder(folder)"
          >
            <AppIcon name="x" :size="13" aria-hidden="true" />
          </button>
        </li>
      </ul>

      <p v-else class="scope-ind__empty">Nessuna cartella nello scope.</p>

      <button
        type="button"
        class="scope-ind__add"
        :disabled="!canEdit"
        :title="busy ? BUSY_HINT : 'Aggiungi una cartella allo scope'"
        @click="addFolder"
      >
        <AppIcon name="plus" :size="13" aria-hidden="true" />
        <span>Aggiungi cartella</span>
      </button>
    </UiPopover>
  </div>
</template>

<style scoped>
.scope-ind {
  position: relative;
  display: inline-flex;
  align-items: center;
}

/* ── Chip: mirrors the other "Agente" chips (ChatToolControls) ── */
.scope-ind__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background var(--duration-fast) ease,
    color var(--duration-fast) ease,
    border-color var(--duration-fast) ease;
}

.scope-ind__chip:hover:not(:disabled) {
  background: var(--surface-3);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.scope-ind__chip--open {
  border-color: var(--accent-border);
  background: var(--surface-3);
  color: var(--text-primary);
}

/* No scope yet — amber posture so the gap is obvious at a glance. */
.scope-ind__chip--empty {
  border-color: var(--warning);
  color: var(--warning);
}

.scope-ind__chip:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.scope-ind__chip-label {
  display: inline;
}

/* ── Popover content ── slot content teleported to <body> by UiPopover.
   These elements are written in THIS component's own template (as the
   default slot passed to UiPopover), so the Vue compiler still stamps them
   with this component's scope attribute — scoped rules keep matching them
   no matter where Teleport relocates the DOM node. Only the popover's own
   root wrapper (owned by UiPopover, see the global block below) is out of
   reach. */
.scope-ind__pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-1) var(--space-2);
}

.scope-ind__pop-title {
  font-family: var(--font-display);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.scope-ind__clear {
  border: none;
  background: none;
  color: var(--accent);
  font-size: var(--text-xs);
  cursor: pointer;
  padding: 0;
}

.scope-ind__clear:hover:not(:disabled) {
  text-decoration: underline;
}

.scope-ind__clear:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ── Hint / error banners ── */
.scope-ind__hint,
.scope-ind__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-1-5);
  padding: var(--space-1-5) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-2xs);
  line-height: var(--leading-snug);
}

.scope-ind__hint {
  color: var(--text-muted);
  background: var(--surface-3);
}

.scope-ind__error {
  color: var(--danger);
  background: var(--danger-faint);
}

/* ── Folder list ── */
.scope-ind__list {
  list-style: none;
  margin: 0 0 var(--space-2);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.scope-ind__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1-5) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--surface-3);
  border: 1px solid var(--border);
}

.scope-ind__item-icon {
  color: var(--text-muted);
}

.scope-ind__item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 auto;
}

.scope-ind__item-name {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope-ind__item-path {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope-ind__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background var(--duration-fast) ease,
    color var(--duration-fast) ease;
}

.scope-ind__remove:hover:not(:disabled) {
  background: var(--danger-faint);
  color: var(--danger);
}

.scope-ind__remove:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.scope-ind__empty {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
}

/* ── Add button ── */
.scope-ind__add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1-5);
  width: 100%;
  padding: var(--space-1-5) var(--space-2);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  background: var(--accent-dim);
  color: var(--accent);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition:
    background var(--duration-fast) ease,
    opacity var(--duration-fast) ease;
}

.scope-ind__add:hover:not(:disabled) {
  background: var(--accent-medium);
}

.scope-ind__add:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}
</style>

<!-- global: .scope-ind__pop is applied via UiPopover's `panel-class` prop
     onto UiPopover's OWN root element (created by UiPopover's own template,
     then teleported to <body>) — it carries UiPopover's scope attribute, not
     this component's, so scoped CSS (with or without :deep()) cannot reach
     it. -->
<style>
.scope-ind__pop {
  max-height: 360px;
  overflow-y: auto;
}
</style>
