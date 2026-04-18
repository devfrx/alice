<script setup lang="ts">
/**
 * NotesPageView — Full-page three-column note editor.
 *
 * Layout: NotesBrowser (280px) | NoteEditor (flex) | NotesBacklinks (240px,
 * only when a note is selected). When the store is in "graph" view mode the
 * editor/backlinks pair is replaced by a full-width graph canvas.
 *
 * Deep-link contract (from router `/notes/:id?`): if `id` is present the
 * matching note is loaded into the store after the initial listing completes.
 * If no note with that id exists the store keeps `currentNote = null`; the
 * embedded NoteEditor is responsible for surfacing the empty/not-found state.
 */
import NotesBrowser from '../components/notes/NotesBrowser.vue'
import NoteEditor from '../components/notes/NoteEditor.vue'
import NotesBacklinks from '../components/notes/NotesBacklinks.vue'
import NotesGraphView from '../components/notes/NotesGraphView.vue'
import { useNotesStore } from '../stores/notes'
import { computed, onMounted, watch } from 'vue'

/** Deep-link prop exposed by the route `/notes/:id?`. */
const props = defineProps<{ id?: string }>()

const store = useNotesStore()
const hasCurrentNote = computed(() => store.currentNote !== null)
const isGraphMode = computed(() => store.viewMode === 'graph')

/** Load the note targeted by the deep link, if provided and different. */
async function syncDeepLink(id: string | undefined): Promise<void> {
    const trimmed = id?.trim()
    if (!trimmed) return
    if (store.currentNote?.id === trimmed) return
    await store.loadNote(trimmed)
}

onMounted(async () => {
    await Promise.all([store.loadAllNotes(), store.loadNotes(), store.loadFolders()])
    await syncDeepLink(props.id)
})

watch(() => props.id, (id) => { void syncDeepLink(id) })
</script>

<template>
    <div class="notes-page" aria-label="Note">
        <NotesBrowser />
        <template v-if="isGraphMode">
            <NotesGraphView />
        </template>
        <template v-else>
            <NoteEditor />
            <NotesBacklinks v-if="hasCurrentNote" />
        </template>
    </div>
</template>

<style scoped>
.notes-page {
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
</style>
