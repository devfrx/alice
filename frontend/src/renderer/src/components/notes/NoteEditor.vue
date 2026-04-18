<script setup lang="ts">
/**
 * NoteEditor — Main editing area for a single note.
 *
 * Features inline title editing, folder/tag management, pin/delete controls,
 * markdown preview toggle, and autosave with 800ms debounce.
 */
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { useNotesStore } from '../../stores/notes'
import { useModal } from '../../composables/useModal'
import { renderMarkdown } from '../../composables/useMarkdown'
import AppIcon from '../ui/AppIcon.vue'

const store = useNotesStore()
const { confirm } = useModal()

/** Navigate to a note when clicking a wikilink in preview. */
function onPreviewClick(e: MouseEvent): void {
    const el = e.target as HTMLElement
    const link = el.closest<HTMLAnchorElement>('a.wikilink')
    if (!link) return
    e.preventDefault()
    const target = link.dataset.target
    if (!target) return
    const match = store.notes.find(
        (n) => n.title.toLowerCase() === target.toLowerCase()
    )
    if (match) store.loadNote(match.id)
}

const isPreview = ref(false)
const localTitle = ref('')
const localContent = ref('')
const localTags = ref<string[]>([])
const newTagInput = ref('')
const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const folderDropdownOpen = ref(false)
const newFolderInput = ref('')
const creatingFolder = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let syncing = false

const note = computed(() => store.currentNote)
const renderedHtml = computed(() =>
    note.value ? renderMarkdown(localContent.value) : ''
)

/** Sync local state when currentNote changes (only on note switch, not on save response). */
watch(note, (n, old) => {
    if (n && n.id !== old?.id) {
        syncing = true
        localTitle.value = n.title
        localContent.value = n.content
        localTags.value = [...n.tags]
        saveStatus.value = 'idle'
        isPreview.value = false
        nextTick(() => { syncing = false })
    }
}, { immediate: true })

/** Autosave content on change. */
watch(localContent, () => {
    if (!note.value || syncing) return
    scheduleSave()
})

onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
})

function scheduleSave(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
    saveStatus.value = 'idle'
    debounceTimer = setTimeout(async () => {
        if (!note.value) return
        saveStatus.value = 'saving'
        await store.updateNote(note.value.id, {
            title: localTitle.value,
            content: localContent.value,
            tags: localTags.value,
        })
        saveStatus.value = store.error ? 'error' : 'saved'
    }, 800)
}

async function saveTitle(): Promise<void> {
    if (!note.value || localTitle.value === note.value.title) return
    saveStatus.value = 'saving'
    await store.updateNote(note.value.id, { title: localTitle.value })
    saveStatus.value = store.error ? 'error' : 'saved'
}

async function togglePin(): Promise<void> {
    if (!note.value) return
    await store.updateNote(note.value.id, { pinned: !note.value.pinned })
}

async function onDelete(): Promise<void> {
    if (!note.value) return
    const ok = await confirm({
        title: 'Elimina nota',
        message: `Eliminare "${note.value.title}"? Questa azione è irreversibile.`,
        type: 'danger',
        confirmText: 'Elimina',
    })
    if (ok) await store.deleteNote(note.value.id)
}

/** Move note to a different folder. */
async function moveToFolder(folderPath: string): Promise<void> {
    if (!note.value || note.value.folder_path === folderPath) {
        folderDropdownOpen.value = false
        return
    }
    saveStatus.value = 'saving'
    await store.updateNote(note.value.id, { folder_path: folderPath })
    await store.loadFolders()
    saveStatus.value = store.error ? 'error' : 'saved'
    folderDropdownOpen.value = false
}

/** Create a new folder and move the note there. */
async function confirmNewFolder(): Promise<void> {
    const path = newFolderInput.value.trim().replace(/^\/+|\/+$/g, '')
    if (!path) {
        creatingFolder.value = false
        return
    }
    creatingFolder.value = false
    newFolderInput.value = ''
    await moveToFolder(path)
}

function openFolderCreation(): void {
    creatingFolder.value = true
    newFolderInput.value = ''
}

function closeFolderDropdown(): void {
    folderDropdownOpen.value = false
    creatingFolder.value = false
    newFolderInput.value = ''
}

function addTag(): void {
    const tag = newTagInput.value.trim().toLowerCase()
    if (!tag || localTags.value.includes(tag)) {
        newTagInput.value = ''
        return
    }
    localTags.value.push(tag)
    newTagInput.value = ''
    scheduleSave()
}

function removeTag(tag: string): void {
    localTags.value = localTags.value.filter((t) => t !== tag)
    scheduleSave()
}

function handleTagKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
        e.preventDefault()
        addTag()
    }
}

function handleTitleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
        e.preventDefault()
            ; (e.target as HTMLInputElement).blur()
    }
}

/**
 * Handle Tab key in the textarea for indentation instead of focus change.
 */
function handleEditorKeydown(e: KeyboardEvent): void {
    if (e.key === 'Tab') {
        e.preventDefault()
        const textarea = e.target as HTMLTextAreaElement
        const start = textarea.selectionStart
        const end = textarea.selectionEnd
        localContent.value =
            localContent.value.substring(0, start) +
            '  ' +
            localContent.value.substring(end)
        nextTick(() => {
            textarea.selectionStart = textarea.selectionEnd = start + 2
        })
    }
}
</script>

<template>
    <main class="editor">
        <!-- Empty state -->
        <div v-if="!note" class="editor__empty">
            <AppIcon name="file" :size="48" :stroke-width="1" style="opacity: 0.3" />
            <p>Seleziona una nota o creane una nuova</p>
        </div>

        <!-- Editor content -->
        <template v-else>
            <!-- Header toolbar -->
            <header class="editor__header">
                <input v-model="localTitle" class="editor__title" placeholder="Titolo nota…" @blur="saveTitle"
                    @keydown="handleTitleKeydown" />

                <div class="editor__actions">
                    <!-- Save status -->
                    <span class="editor__status" :class="{
                        'editor__status--saving': saveStatus === 'saving',
                        'editor__status--saved': saveStatus === 'saved',
                        'editor__status--error': saveStatus === 'error',
                    }">
                        <template v-if="saveStatus === 'saving'">Salvataggio…</template>
                        <template v-else-if="saveStatus === 'saved'">Salvato &#10003;</template>
                        <template v-else-if="saveStatus === 'error'">Errore ✕</template>
                    </span>

                    <!-- Preview toggle -->
                    <button class="editor__btn" :class="{ 'editor__btn--active': isPreview }" title="Anteprima Markdown"
                        @click="isPreview = !isPreview">
                        <AppIcon name="eye" :size="14" />
                    </button>

                    <!-- Pin toggle -->
                    <button class="editor__btn" :class="{ 'editor__btn--active': note.pinned }"
                        :title="note.pinned ? 'Rimuovi fissaggio' : 'Fissa nota'" @click="togglePin">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z" />
                        </svg>
                    </button>

                    <!-- Delete -->
                    <button class="editor__btn editor__btn--danger" title="Elimina nota" @click="onDelete">
                        <AppIcon name="trash" :size="14" />
                    </button>
                </div>
            </header>

            <!-- Folder selector -->
            <div class="editor__folder">
                <div class="editor__folder-current" @click="folderDropdownOpen = !folderDropdownOpen">
                    <AppIcon name="folder" :size="12" />
                    <span>{{ note.folder_path || '/' }}</span>
                    <AppIcon name="chevron-down" :size="10" :stroke-width="2.5" class="editor__folder-chevron"
                        :class="{ 'editor__folder-chevron--open': folderDropdownOpen }" />
                </div>

                <!-- Dropdown -->
                <div v-if="folderDropdownOpen" class="editor__folder-dropdown">
                    <div class="editor__folder-backdrop" @click="closeFolderDropdown" />
                    <div class="editor__folder-menu">
                        <button class="editor__folder-option"
                            :class="{ 'editor__folder-option--active': note.folder_path === '' }"
                            @click="moveToFolder('')">
                            / (root)
                        </button>
                        <button v-for="f in store.folders.filter((f) => f.path)" :key="f.path"
                            class="editor__folder-option"
                            :class="{ 'editor__folder-option--active': note.folder_path === f.path }"
                            @click="moveToFolder(f.path)">
                            {{ f.path }}
                        </button>

                        <!-- New folder inline -->
                        <div v-if="creatingFolder" class="editor__folder-new">
                            <input v-model="newFolderInput" class="editor__folder-new-input"
                                placeholder="percorso/cartella" autofocus @keydown.enter.prevent="confirmNewFolder"
                                @keydown.escape="creatingFolder = false" />
                        </div>
                        <button v-else class="editor__folder-option editor__folder-option--create"
                            @click="openFolderCreation">
                            + Nuova cartella…
                        </button>
                    </div>
                </div>
            </div>

            <!-- Tags bar -->
            <div class="editor__tags">
                <span v-for="tag in localTags" :key="tag" class="editor__tag">
                    #{{ tag }}
                    <button class="editor__tag-remove" @click="removeTag(tag)">&times;</button>
                </span>
                <input v-model="newTagInput" class="editor__tag-input" placeholder="+ aggiungi tag"
                    @keydown="handleTagKeydown" />
            </div>

            <!-- Content area -->
            <div class="editor__content">
                <!-- Edit mode -->
                <textarea v-if="!isPreview" v-model="localContent" class="editor__textarea"
                    placeholder="Scrivi in Markdown…" @keydown="handleEditorKeydown" />

                <!-- Preview mode -->
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div v-else class="editor__preview markdown-body" v-html="renderedHtml" @click="onPreviewClick" />
            </div>
        </template>
    </main>
</template>

<style scoped>
.editor {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    height: 100%;
    overflow: hidden;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
}

.editor__empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-4);
    color: var(--text-muted);
    font-size: var(--text-sm);
}

.editor__header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
    background: var(--surface-1);
}

.editor__title {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: var(--text-md);
    font-weight: 600;
    outline: none;
    padding: var(--space-1) 0;
}

.editor__title::placeholder {
    color: var(--text-muted);
}

.editor__actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.editor__status {
    font-size: var(--text-xs);
    color: var(--text-muted);
    min-width: 90px;
    text-align: right;
    transition: color var(--transition-fast);
}

.editor__status--saving {
    color: var(--warning);
}

.editor__status--saved {
    color: var(--success);
}

.editor__status--error {
    color: var(--danger);
}

.editor__btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: none;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.editor__btn:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.editor__btn--active {
    background: var(--accent-dim);
    color: var(--accent);
    border-color: var(--accent-border);
}

.editor__btn--danger:hover {
    background: var(--danger-hover);
    color: var(--danger);
    border-color: var(--danger-border);
}

/* ------------------------------------------------- Folder selector */
.editor__folder {
    position: relative;
    padding: var(--space-1) var(--space-4);
    border-bottom: 1px solid var(--border);
}

.editor__folder-current {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 2px var(--space-2);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.editor__folder-current:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.editor__folder-chevron {
    transition: transform var(--transition-fast);
}

.editor__folder-chevron--open {
    transform: rotate(180deg);
}

.editor__folder-dropdown {
    position: absolute;
    top: 100%;
    left: var(--space-4);
    z-index: 50;
}

.editor__folder-backdrop {
    position: fixed;
    inset: 0;
    z-index: -1;
}

.editor__folder-menu {
    min-width: 200px;
    max-height: 240px;
    overflow-y: auto;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-md);
    padding: var(--space-1) 0;
}

.editor__folder-option {
    display: block;
    width: 100%;
    padding: var(--space-1-5) var(--space-3);
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.editor__folder-option:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.editor__folder-option--active {
    color: var(--accent);
}

.editor__folder-option--create {
    color: var(--accent);
    border-top: 1px solid var(--border);
    margin-top: var(--space-1);
    padding-top: var(--space-2);
}

.editor__folder-new {
    padding: var(--space-1) var(--space-2);
    border-top: 1px solid var(--border);
    margin-top: var(--space-1);
}

.editor__folder-new-input {
    width: 100%;
    padding: var(--space-1) var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    outline: none;
}

.editor__folder-new-input:focus {
    border-color: var(--accent-dim);
}

.editor__tags {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--border);
    min-height: 32px;
}

.editor__tag {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 2px var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-xs);
}

.editor__tag-remove {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: var(--text-sm);
    line-height: 1;
    padding: 0 2px;
    transition: color var(--transition-fast);
}

.editor__tag-remove:hover {
    color: var(--danger);
}

.editor__tag-input {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: var(--text-xs);
    outline: none;
    min-width: 80px;
    padding: 2px 0;
}

.editor__tag-input::placeholder {
    color: var(--text-muted);
}

.editor__content {
    flex: 1;
    overflow: hidden;
    display: flex;
}

.editor__textarea {
    flex: 1;
    width: 100%;
    padding: var(--space-4);
    background: var(--surface-0);
    border: none;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    line-height: 1.7;
    resize: none;
    outline: none;
    overflow-y: auto;
    max-width: 720px;
    margin: 0 auto;
}

.editor__textarea::placeholder {
    color: var(--text-muted);
}

.editor__textarea::-webkit-scrollbar {
    width: 4px;
}

.editor__textarea::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: 2px;
}

.editor__preview {
    flex: 1;
    padding: var(--space-4);
    overflow-y: auto;
    max-width: 720px;
    margin: 0 auto;
    color: var(--text-primary);
    font-size: var(--text-sm);
    line-height: 1.7;
}

.editor__preview::-webkit-scrollbar {
    width: 4px;
}

.editor__preview::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: 2px;
}
</style>
