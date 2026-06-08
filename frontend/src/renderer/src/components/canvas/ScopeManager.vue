<script setup lang="ts">
/**
 * ScopeManager — Standalone panel for editing a conversation's workspace scope.
 *
 * The *scope* is the set of filesystem folders the scoped Terminal plugin is
 * confined to. This panel lets the user add (via the native directory picker),
 * remove, and clear those folders for the active conversation.
 *
 * ## Data flow
 * On mount and whenever the conversation changes, the scope is fetched once via
 * {@link useScopeStore.ensureForConversation}. Live updates arrive out-of-band
 * through the `scope.updated` events-WS frame (folded by the scope store), so no
 * polling is needed here.
 *
 * ## Idle guard
 * The backend only accepts scope mutations while the conversation is idle (no
 * turn running). The UI mirrors this two ways:
 * - Add / remove / clear are disabled while the current conversation is
 *   streaming ({@link useChatStore.isStreamingCurrentConversation}), with an
 *   explanatory hint.
 * - As a backstop (a turn may start while the native picker is open), a `PUT` /
 *   `DELETE` rejected with {@link ApiError} `status === 409` ("scope_locked")
 *   is caught and surfaced as a transient inline message.
 *
 * Self-contained: it derives its subject from the chat store and is not mounted
 * anywhere yet — it will be embedded inside the Terminal module in a later task.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import { useChatStore } from '../../stores/chat'
import { useScopeStore } from '../../stores/scope'
import { ApiError } from '../../services/api'

const BUSY_HINT = 'Lo scope è modificabile solo a generazione ferma.'
const LOCKED_MSG = 'Scope bloccato: una generazione è in corso.'
const GENERIC_ERR = 'Impossibile aggiornare lo scope. Riprova.'

const chatStore = useChatStore()
const scopeStore = useScopeStore()

/** Active conversation id, or null when none is open. */
const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

/** Scope folders for the active conversation (empty when none). */
const folders = computed<string[]>(() =>
  conversationId.value ? scopeStore.foldersFor(conversationId.value) : [],
)

/** True while the current conversation is streaming — gates mutations. */
const busy = computed<boolean>(() => chatStore.isStreamingCurrentConversation)

/** Whether scope mutations are currently allowed in the UI. */
const canEdit = computed<boolean>(() => conversationId.value !== null && !busy.value)

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

onMounted(() => load(conversationId.value))
watch(conversationId, (id) => load(id))
onBeforeUnmount(() => {
  if (errorTimer) clearTimeout(errorTimer)
})

/** Last path segment, used as the friendlier primary label for a folder. */
function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] ?? path
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
  const id = conversationId.value
  if (!id || !canEdit.value) return
  const dir = await window.electron.fileOps.selectDirectory()
  if (!dir) return
  if (folders.value.includes(dir)) return // already in scope — skip
  await mutate(() => scopeStore.setFolders(id, [...folders.value, dir]))
}

/** Remove a single folder from the scope. */
async function removeFolder(target: string): Promise<void> {
  const id = conversationId.value
  if (!id || !canEdit.value) return
  await mutate(() => scopeStore.setFolders(id, folders.value.filter((f) => f !== target)))
}

/** Clear all folders from the scope. */
async function clearAll(): Promise<void> {
  const id = conversationId.value
  if (!id || !canEdit.value) return
  await mutate(() => scopeStore.clear(id))
}
</script>

<template>
  <section class="scope" aria-label="Scope cartelle del workspace">
    <header class="scope__header">
      <div class="scope__heading">
        <AppIcon name="folder" :size="15" class="scope__heading-icon" aria-hidden="true" />
        <div class="scope__heading-text">
          <h3 class="scope__title">Scope cartelle</h3>
          <p class="scope__subtitle">Cartelle a cui l'assistente può accedere dal terminale.</p>
        </div>
      </div>
      <button
        type="button"
        class="scope__btn scope__btn--accent"
        :disabled="!canEdit"
        :title="busy ? BUSY_HINT : 'Aggiungi una cartella allo scope'"
        @click="addFolder"
      >
        <AppIcon name="plus" :size="14" aria-hidden="true" />
        <span>Aggiungi</span>
      </button>
    </header>

    <p v-if="busy" class="scope__hint" role="status">
      <AppIcon name="lightning" :size="13" aria-hidden="true" />
      <span>{{ BUSY_HINT }}</span>
    </p>

    <p v-if="error" class="scope__error" role="alert">
      <AppIcon name="alert-triangle" :size="13" aria-hidden="true" />
      <span>{{ error }}</span>
    </p>

    <div class="scope__body">
      <ul v-if="folders.length > 0" class="scope__list" role="list">
        <li v-for="folder in folders" :key="folder" class="scope__item">
          <AppIcon name="folder" :size="15" class="scope__item-icon" aria-hidden="true" />
          <span class="scope__item-text">
            <span class="scope__item-name">{{ folderName(folder) }}</span>
            <span class="scope__item-path" :title="folder">{{ folder }}</span>
          </span>
          <button
            type="button"
            class="scope__remove"
            :disabled="!canEdit"
            :title="busy ? BUSY_HINT : 'Rimuovi dallo scope'"
            :aria-label="`Rimuovi ${folder} dallo scope`"
            @click="removeFolder(folder)"
          >
            <AppIcon name="x" :size="14" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <UiEmptyState
        v-else
        icon="folder"
        title="Nessuna cartella nello scope"
        subtitle="Aggiungi una cartella per delimitare l'area di lavoro dell'assistente."
      />
    </div>

    <footer v-if="folders.length > 0" class="scope__footer">
      <button
        type="button"
        class="scope__btn scope__btn--ghost"
        :disabled="!canEdit"
        :title="busy ? BUSY_HINT : 'Rimuovi tutte le cartelle'"
        @click="clearAll"
      >
        <AppIcon name="trash" :size="14" aria-hidden="true" />
        <span>Svuota scope</span>
      </button>
    </footer>
  </section>
</template>

<style scoped>
.scope {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: var(--font-sans);
}

/* ── Header ─────────────────────────────────────────────────── */
.scope__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--border);
}

.scope__heading {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  min-width: 0;
}

.scope__heading-icon {
  color: var(--accent);
  margin-top: 2px;
}

.scope__heading-text {
  min-width: 0;
}

.scope__title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.scope__subtitle {
  margin: var(--space-0-5) 0 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--leading-snug);
}

/* ── Buttons ────────────────────────────────────────────────── */
.scope__btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  flex-shrink: 0;
  padding: var(--space-1-5) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.scope__btn--accent {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

.scope__btn--accent:hover:not(:disabled) {
  background: var(--accent-medium);
}

.scope__btn--ghost {
  background: transparent;
  border-color: var(--border);
  color: var(--text-secondary);
}

.scope__btn--ghost:hover:not(:disabled) {
  border-color: var(--border-hover);
  color: var(--text-primary);
  background: var(--surface-hover);
}

.scope__btn:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ── Hint / error banners ───────────────────────────────────── */
.scope__hint,
.scope__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}

.scope__hint {
  color: var(--text-muted);
  background: var(--surface-inset);
}

.scope__error {
  color: var(--danger);
  background: var(--danger-faint);
}

/* ── Body / folder list ─────────────────────────────────────── */
.scope__body {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
}

.scope__list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.scope__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--border);
}

.scope__item-icon {
  color: var(--text-muted);
}

.scope__item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 auto;
}

.scope__item-name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope__item-path {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.scope__remove:hover:not(:disabled) {
  background: var(--danger-hover);
  color: var(--danger);
}

.scope__remove:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ── Footer ─────────────────────────────────────────────────── */
.scope__footer {
  display: flex;
  justify-content: flex-end;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border);
}
</style>
