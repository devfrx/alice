<script setup lang="ts">
/**
 * NotesPageView — Full-page three-column note editor.
 *
 * Layout: NotesBrowser (280px) | NoteEditor (flex) | NotesBacklinks (240px, conditional)
 */
import NotesBrowser from '../components/notes/NotesBrowser.vue'
import NoteEditor from '../components/notes/NoteEditor.vue'
import NotesBacklinks from '../components/notes/NotesBacklinks.vue'
import NotesGraphView from '../components/notes/NotesGraphView.vue'
import { useNotesStore } from '../stores/notes'
import { computed, onMounted } from 'vue'

const store = useNotesStore()
const hasCurrentNote = computed(() => store.currentNote !== null)
const isGraphMode = computed(() => store.viewMode === 'graph')

onMounted(() => {
    store.loadAllNotes()
    store.loadNotes()
    store.loadFolders()
})
</script>

<template>
    <div class="notes-page">
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
