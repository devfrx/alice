<script setup lang="ts">
/**
 * NotesBrowser — Left sidebar panel for browsing, searching, and filtering notes.
 *
 * Shows search input, new note button, folders, tags, markdown mini-guide,
 * and the scrollable note list with pinned notes, hover action buttons,
 * and context info.
 */
import { ref, watch, onUnmounted } from 'vue'
import { useNotesStore } from '../../stores/notes'
import { useModal } from '../../composables/useModal'

const store = useNotesStore()
const { confirm } = useModal()

const localSearch = ref(store.searchQuery)
const guideOpen = ref(false)
const showNewFolder = ref(false)
const newFolderPath = ref('')
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(localSearch, (val) => {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
        if (val.trim()) {
            store.searchNotes(val.trim())
        } else {
            store.clearSearch()
        }
    }, 300)
})

onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
})

async function onCreateNote(): Promise<void> {
    await store.createNote('Nuova nota')
}

/** Create a new folder by creating a note inside it. */
async function confirmNewFolder(): Promise<void> {
    const path = newFolderPath.value.trim().replace(/^\/+|\/+$/g, '')
    if (!path) {
        showNewFolder.value = false
        return
    }
    showNewFolder.value = false
    newFolderPath.value = ''
    await store.createNoteInFolder('Nuova nota', path)
}

/** Delete a folder — ask user for mode (move notes to root or delete all). */
async function onDeleteFolder(folderPath: string, count: number): Promise<void> {
    const ok = await confirm({
        title: 'Elimina cartella',
        message:
            `"${folderPath}" contiene ${count} nota/e.\n\n` +
            `Scegli "Conferma" per spostare le note alla root ed eliminare la cartella, ` +
            `oppure annulla.`,
        type: 'danger',
        confirmText: 'Sposta a root e elimina',
    })
    if (ok) await store.deleteFolder(folderPath, 'move')
}

function selectNote(id: string): void {
    store.loadNote(id)
}

function isSelected(id: string): boolean {
    return store.currentNote?.id === id
}

async function togglePin(noteId: string, currentPinned: boolean): Promise<void> {
    await store.updateNote(noteId, { pinned: !currentPinned })
}

async function onDeleteNote(noteId: string, noteTitle: string): Promise<void> {
    const ok = await confirm({
        title: 'Elimina nota',
        message: `Eliminare "${noteTitle}"? Questa azione è irreversibile.`,
        type: 'danger',
        confirmText: 'Elimina',
    })
    if (ok) await store.deleteNote(noteId)
}

/** Format relative time in Italian. */
function relativeTime(dateStr: string): string {
    if (!dateStr) return '—'
    const ts = new Date(dateStr).getTime()
    if (isNaN(ts)) return '—'
    const diff = Date.now() - ts
    const mins = Math.floor(diff / 60_000)
    if (mins < 1) return 'ora'
    if (mins < 60) return `${mins}m fa`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h fa`
    const days = Math.floor(hours / 24)
    if (days < 30) return `${days}g fa`
    return new Date(dateStr).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

/** Get a short preview from content (first ~80 chars). */
function preview(content: string): string {
    const clean = content.replace(/[#*_`>\[\]]/g, '').trim()
    return clean.length > 80 ? clean.slice(0, 80) + '…' : clean
}
</script>

<template>
    <aside class="browser">
        <!-- Search -->
        <div class="browser__search">
            <input v-model="localSearch" type="text" class="browser__search-input" placeholder="Cerca note…" />
        </div>

        <!-- New note + view toggle row -->
        <div class="browser__toolbar">
            <button class="browser__new-btn" @click="onCreateNote">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                Nuova nota
            </button>
            <div class="browser__view-toggle">
                <button class="browser__view-btn" :class="{ 'browser__view-btn--active': store.viewMode === 'list' }"
                    title="Vista lista" @click="store.setViewMode('list')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round">
                        <line x1="4" y1="6" x2="20" y2="6" />
                        <line x1="4" y1="12" x2="20" y2="12" />
                        <line x1="4" y1="18" x2="20" y2="18" />
                    </svg>
                </button>
                <button class="browser__view-btn" :class="{ 'browser__view-btn--active': store.viewMode === 'graph' }"
                    title="Vista grafo" @click="store.setViewMode('graph')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round">
                        <circle cx="6" cy="6" r="2" />
                        <circle cx="18" cy="8" r="2" />
                        <circle cx="12" cy="18" r="2" />
                        <line x1="7.5" y1="7.5" x2="10.5" y2="16.5" />
                        <line x1="16.5" y1="9.5" x2="13.5" y2="16.5" />
                    </svg>
                </button>
            </div>
        </div>

        <!-- Markdown & backlinks guide (collapsible) -->
        <div class="browser__section browser__guide">
            <button class="browser__guide-toggle" @click="guideOpen = !guideOpen">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                    class="browser__guide-chevron" :class="{ 'browser__guide-chevron--open': guideOpen }">
                    <polyline points="9 18 15 12 9 6" />
                </svg>
                <span class="browser__section-label" style="margin-bottom: 0">Guida Markdown</span>
            </button>
            <div v-if="guideOpen" class="browser__guide-body">
                <table class="browser__guide-table">
                    <tbody>
                        <tr>
                            <td class="browser__guide-syntax"># Titolo</td>
                            <td>Intestazione</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">**grassetto**</td>
                            <td>Grassetto</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">*corsivo*</td>
                            <td>Corsivo</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">~~barrato~~</td>
                            <td>Barrato</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">- elemento</td>
                            <td>Lista puntata</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">1. elemento</td>
                            <td>Lista numerata</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">> citazione</td>
                            <td>Blocco citazione</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">`codice`</td>
                            <td>Codice inline</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">```lang</td>
                            <td>Blocco codice</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">[testo](url)</td>
                            <td>Link</td>
                        </tr>
                        <tr>
                            <td class="browser__guide-syntax">---</td>
                            <td>Separatore</td>
                        </tr>
                    </tbody>
                </table>
                <div class="browser__guide-divider" />
                <div class="browser__guide-subtitle">Backlinks</div>
                <p class="browser__guide-text">
                    Usa <code>[[Nome Nota]]</code> per creare un link ad un'altra nota.
                    Le note collegate appariranno automaticamente nella sezione backlinks dell'editor.
                </p>
                <p class="browser__guide-text">
                    Puoi anche usare <code>[[Nota|testo visibile]]</code> per personalizzare il testo del link.
                </p>
            </div>
        </div>

        <!-- Folders -->
        <div class="browser__section">
            <div class="browser__section-header">
                <div class="browser__section-label">Cartelle</div>
                <button class="browser__section-add" title="Nuova cartella" @click="showNewFolder = !showNewFolder">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="12" y1="5" x2="12" y2="19" />
                        <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                </button>
            </div>

            <!-- New folder inline input -->
            <div v-if="showNewFolder" class="browser__new-folder">
                <input v-model="newFolderPath" class="browser__new-folder-input" placeholder="percorso/cartella"
                    autofocus @keydown.enter.prevent="confirmNewFolder" @keydown.escape="showNewFolder = false" />
            </div>

            <button class="browser__folder" :class="{ 'browser__folder--active': store.activeFolder === null }"
                @click="store.setFolder(null)">
                <span>Tutte</span>
                <span class="browser__folder-count">{{ store.total }}</span>
            </button>
            <button v-for="folder in store.folders" :key="folder.path" class="browser__folder"
                :class="{ 'browser__folder--active': store.activeFolder === folder.path }"
                @click="store.setFolder(folder.path)">
                <span class="browser__folder-name">{{ folder.path || '/' }}</span>
                <span class="browser__folder-right">
                    <span class="browser__folder-count">{{ folder.count }}</span>
                    <button v-if="folder.path" class="browser__folder-delete" title="Elimina cartella"
                        @click.stop="onDeleteFolder(folder.path, folder.count)">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </span>
            </button>
        </div>

        <!-- Tags -->
        <div v-if="store.allTags.length > 0" class="browser__section">
            <div class="browser__section-label">Tag</div>
            <div class="browser__tags">
                <button v-for="tag in store.allTags" :key="tag" class="browser__tag"
                    :class="{ 'browser__tag--active': store.activeTags.includes(tag) }" @click="store.toggleTag(tag)">
                    #{{ tag }}
                </button>
            </div>
        </div>

        <!-- Note list -->
        <div class="browser__list">
            <div v-for="note in store.notes" :key="note.id" class="browser__item" :class="{
                'browser__item--selected': isSelected(note.id),
                'browser__item--pinned': note.pinned,
            }" @click="selectNote(note.id)">
                <div class="browser__item-header">
                    <span v-if="note.pinned" class="browser__pin" title="Fissata">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z" />
                        </svg>
                    </span>
                    <span class="browser__item-title">{{ note.title }}</span>
                </div>
                <div class="browser__item-preview">{{ preview(note.content) }}</div>
                <div class="browser__item-meta">{{ relativeTime(note.updated_at) }}</div>

                <!-- Hover action buttons (ConversationList pattern) -->
                <div class="browser__item-actions" @click.stop>
                    <button class="browser__item-action" :title="note.pinned ? 'Rimuovi fissaggio' : 'Fissa nota'"
                        @click="togglePin(note.id, note.pinned)">
                        <svg width="11" height="11" viewBox="0 0 24 24" :fill="note.pinned ? 'currentColor' : 'none'"
                            stroke="currentColor" stroke-width="2">
                            <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z" />
                        </svg>
                    </button>
                    <button class="browser__item-action browser__item-action--danger" title="Elimina nota"
                        @click="onDeleteNote(note.id, note.title)">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6l-1 14H6L5 6" />
                            <path d="M10 11v6" />
                            <path d="M14 11v6" />
                            <path d="M9 6V4h6v2" />
                        </svg>
                    </button>
                </div>
            </div>

            <div v-if="!store.loading && store.notes.length === 0" class="browser__empty">
                Nessuna nota trovata
            </div>
        </div>

        <!-- Loading indicator -->
        <div v-if="store.loading" class="browser__loading">Caricamento…</div>

        <!-- Error banner -->
        <div v-if="store.error" class="browser__error">{{ store.error }}</div>
    </aside>
</template>

<style scoped>
.browser {
    width: 280px;
    min-width: 280px;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--surface-1);
    border-right: 1px solid var(--border);
    overflow: hidden;
}

.browser__search {
    padding: var(--space-3);
    border-bottom: 1px solid var(--border);
}

.browser__search-input {
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    outline: none;
    transition: border-color var(--transition-fast);
}

.browser__search-input::placeholder {
    color: var(--text-muted);
}

.browser__search-input:focus {
    border-color: var(--accent-dim);
    box-shadow: var(--focus-ring-shadow);
}

.browser__toolbar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
}

.browser__new-btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex: 1;
    padding: var(--space-2) var(--space-3);
    background: var(--accent-dim);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--accent);
    font-size: var(--text-sm);
    cursor: pointer;
    transition: background var(--transition-fast);
}

.browser__new-btn:hover {
    background: rgba(232, 220, 200, 0.15);
}

.browser__view-toggle {
    display: flex;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
}

.browser__view-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: var(--surface-2);
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.browser__view-btn:first-child {
    border-right: 1px solid var(--border);
}

.browser__view-btn:hover {
    color: var(--text-primary);
}

.browser__view-btn--active {
    background: var(--accent-dim);
    color: var(--accent);
}

/* ------------------------------------------------- Guide section */
.browser__guide {
    padding: 0;
}

.browser__guide-toggle {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-muted);
    transition: color var(--transition-fast);
}

.browser__guide-toggle:hover {
    color: var(--text-secondary);
}

.browser__guide-toggle:focus-visible {
    box-shadow: var(--focus-ring-shadow);
    outline: none;
}

.browser__guide-chevron {
    transition: transform var(--transition-fast);
    flex-shrink: 0;
}

.browser__guide-chevron--open {
    transform: rotate(90deg);
}

.browser__guide-body {
    padding: 0 var(--space-3) var(--space-2);
}

.browser__guide-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-xs);
    line-height: 1.6;
}

.browser__guide-table td {
    padding: 1px var(--space-1);
    color: var(--text-secondary);
}

.browser__guide-syntax {
    font-family: var(--font-mono);
    color: var(--accent);
    white-space: nowrap;
    width: 1%;
}

.browser__guide-divider {
    height: 1px;
    background: var(--border);
    margin: var(--space-2) 0;
}

.browser__guide-subtitle {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: var(--space-1);
}

.browser__guide-text {
    font-size: var(--text-xs);
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0 0 var(--space-1);
}

.browser__guide-text code {
    font-family: var(--font-mono);
    color: var(--accent);
    background: var(--surface-2);
    padding: 1px 4px;
    border-radius: var(--radius-xs);
    font-size: inherit;
}

/* ------------------------------------------------- Sections */
.browser__section {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
}

.browser__section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.browser__section-add {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    background: none;
    border: none;
    border-radius: var(--radius-xs);
    color: var(--text-muted);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.browser__section-add:hover {
    background: var(--surface-2);
    color: var(--accent);
}

.browser__new-folder {
    padding: var(--space-1) 0;
}

.browser__new-folder-input {
    width: 100%;
    padding: var(--space-1) var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-xs);
    outline: none;
}

.browser__new-folder-input:focus {
    border-color: var(--accent-dim);
}

.browser__section-label {
    font-size: var(--text-xs);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-1);
}

.browser__folder {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    padding: var(--space-1) var(--space-2);
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.browser__folder:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.browser__folder--active {
    background: var(--accent-dim);
    color: var(--accent);
}

.browser__folder-count {
    font-size: var(--text-xs);
    color: var(--text-muted);
}

.browser__folder-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}

.browser__folder-right {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
}

.browser__folder-delete {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    background: none;
    border: none;
    border-radius: var(--radius-xs);
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), color var(--transition-fast);
}

.browser__folder:hover .browser__folder-delete {
    opacity: 1;
}

.browser__folder-delete:hover {
    color: var(--danger);
}

.browser__tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
}

.browser__tag {
    padding: 2px var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.browser__tag:hover {
    background: var(--surface-3);
    color: var(--text-primary);
}

.browser__tag--active {
    background: var(--accent-dim);
    color: var(--accent);
    border-color: rgba(232, 220, 200, 0.2);
}

/* ------------------------------------------------- Note list */
.browser__list {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-2) 0;
}

.browser__list::-webkit-scrollbar {
    width: 4px;
}

.browser__list::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: 2px;
}

.browser__item {
    position: relative;
    padding: var(--space-2) var(--space-3);
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: background var(--transition-fast), border-color var(--transition-fast);
}

.browser__item:hover {
    background: var(--surface-2);
}

.browser__item--selected {
    background: var(--accent-dim);
    border-left-color: var(--accent);
}

.browser__item--pinned {
    border-top: 1px solid var(--border);
}

.browser__item--pinned:first-child {
    border-top: none;
}

.browser__item-header {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    margin-bottom: 2px;
    padding-right: 48px;
}

.browser__pin {
    color: var(--accent);
    flex-shrink: 0;
    display: flex;
    align-items: center;
}

.browser__item-title {
    font-size: var(--text-sm);
    color: var(--text-primary);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.browser__item-preview {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.browser__item-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin-top: 2px;
}

/* ------------------------------------------------- Hover action buttons */
.browser__item-actions {
    position: absolute;
    top: var(--space-2);
    right: var(--space-2);
    display: flex;
    gap: 2px;
    opacity: 0;
    pointer-events: none;
    background: var(--surface-1);
    padding: var(--space-0-5);
    border-radius: var(--radius-sm);
    transition: opacity var(--transition-fast);
}

.browser__item:hover .browser__item-actions {
    opacity: 1;
    pointer-events: auto;
}

.browser__item-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.browser__item-action:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
}

.browser__item-action:focus-visible {
    box-shadow: var(--focus-ring-shadow);
    outline: none;
}

.browser__item-action--danger:hover {
    color: var(--danger);
}

/* ------------------------------------------------- Empty / Loading */
.browser__empty {
    padding: var(--space-6);
    text-align: center;
    color: var(--text-muted);
    font-size: var(--text-sm);
}

.browser__loading {
    padding: var(--space-3);
    text-align: center;
    color: var(--text-muted);
    font-size: var(--text-xs);
}

.browser__error {
    padding: var(--space-2) var(--space-3);
    color: var(--error, #f87171);
    font-size: var(--text-xs);
    background: rgba(248, 113, 113, 0.08);
    border-top: 1px solid rgba(248, 113, 113, 0.2);
}

/* ------------------------------------------------- Reduced motion */
@media (prefers-reduced-motion: reduce) {

    .browser__guide-chevron,
    .browser__item-actions,
    .browser__item-action,
    .browser__item,
    .browser__search-input,
    .browser__new-btn,
    .browser__folder,
    .browser__tag {
        transition: none;
    }
}
</style>
