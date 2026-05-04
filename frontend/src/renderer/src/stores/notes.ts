/**
 * Pinia store for AL\CE note system (Obsidian-like).
 *
 * Provides CRUD operations, search, folder/tag filtering
 * over the backend notes service at `/api/notes`.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../services/api'
import type { Note, NoteFolder } from '../types/notes'

export const useNotesStore = defineStore('notes', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  const notes = ref<Note[]>([])
  const allNotes = ref<Note[]>([])
  const total = ref<number>(0)
  const currentNote = ref<Note | null>(null)
  const folders = ref<NoteFolder[]>([])
  const activeFolder = ref<string | null>(null)
  const activeTags = ref<string[]>([])
  const searchQuery = ref<string>('')
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  /** Current view mode for the notes page. */
  const viewMode = ref<'list' | 'graph'>('list')

  // -----------------------------------------------------------------------
  // Computed
  // -----------------------------------------------------------------------

  /** All unique tags from loaded notes. */
  const allTags = computed<string[]>(() => {
    const tagSet = new Set<string>()
    for (const note of notes.value) {
      for (const tag of note.tags) tagSet.add(tag)
    }
    return [...tagSet].sort()
  })

  /** Notes that link to the current note via wikilinks (uses allNotes for cross-folder coverage). */
  const backlinks = computed<Note[]>(() => {
    if (!currentNote.value) return []
    const title = currentNote.value.title.toLowerCase()
    return allNotes.value.filter(
      (n) =>
        n.id !== currentNote.value!.id &&
        n.wikilinks.some((w) => w.toLowerCase() === title)
    )
  })

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /** Fetch ALL notes (unfiltered) for graph view and backlinks. */
  async function loadAllNotes(): Promise<void> {
    try {
      const data = await api.getNotes({} as Parameters<typeof api.getNotes>[0])
      allNotes.value = data.notes
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Fetch notes with current filters applied. */
  async function loadNotes(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string | number | boolean> = {}
      if (activeFolder.value) params.folder = activeFolder.value
      if (activeTags.value.length > 0) params.tags = activeTags.value.join(',')
      if (searchQuery.value) params.q = searchQuery.value
      const data = await api.getNotes(params as Parameters<typeof api.getNotes>[0])
      notes.value = data.notes
      total.value = data.total
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Load a single note by ID and set as current. */
  async function loadNote(id: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      currentNote.value = await api.getNote(id)
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Create a new note and set it as current. */
  async function createNote(title: string, content = ''): Promise<void> {
    saving.value = true
    error.value = null
    try {
      const note = await api.createNote({
        title,
        content,
        folder_path: activeFolder.value ?? undefined,
      })
      currentNote.value = note
      allNotes.value.push(note)
      await loadNotes()
      await loadFolders()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      saving.value = false
    }
  }

  /** Create a note in a specific folder, set that folder active, and open the note. */
  async function createNoteInFolder(title: string, folderPath: string): Promise<void> {
    saving.value = true
    error.value = null
    try {
      const note = await api.createNote({
        title,
        content: '',
        folder_path: folderPath,
      })
      currentNote.value = note
      allNotes.value.push(note)
      activeFolder.value = folderPath
      await loadFolders()
      await loadNotes()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      saving.value = false
    }
  }

  /** Update a note. Refreshes the list and current note reference. */
  async function updateNote(
    id: string,
    data: Parameters<typeof api.updateNote>[1]
  ): Promise<void> {
    saving.value = true
    error.value = null
    try {
      const updated = await api.updateNote(id, data)
      if (currentNote.value?.id === id) {
        currentNote.value = updated
      }
      const idx = notes.value.findIndex((n) => n.id === id)
      if (idx !== -1) notes.value[idx] = updated
      const allIdx = allNotes.value.findIndex((n) => n.id === id)
      if (allIdx !== -1) allNotes.value[allIdx] = updated
      if (data.folder_path !== undefined) {
        await loadFolders()
        await loadNotes()
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      saving.value = false
    }
  }

  /** Delete a note by ID. Clears current if it matches. */
  async function deleteNote(id: string): Promise<void> {
    error.value = null
    try {
      await api.deleteNote(id)
      notes.value = notes.value.filter((n) => n.id !== id)
      allNotes.value = allNotes.value.filter((n) => n.id !== id)
      total.value = Math.max(0, total.value - 1)
      if (currentNote.value?.id === id) {
        currentNote.value = null
      }
      await loadFolders()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Delete a folder. Notes are moved to root or deleted based on mode. */
  async function deleteFolder(
    folderPath: string,
    mode: 'move' | 'delete' = 'move'
  ): Promise<void> {
    error.value = null
    try {
      await api.deleteFolder(folderPath, mode)
      if (activeFolder.value === folderPath) {
        activeFolder.value = null
      }
      if (
        currentNote.value &&
        currentNote.value.folder_path === folderPath &&
        mode === 'delete'
      ) {
        currentNote.value = null
      }
      await loadFolders()
      await loadNotes()
      await loadAllNotes()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Search notes via backend full-text search. */
  async function searchNotes(query: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.searchNotes(
        query,
        activeFolder.value ?? undefined,
        activeTags.value.length > 0 ? activeTags.value : undefined
      )
      notes.value = data.results.map(({ score, ...note }) => note)
      total.value = data.results.length
      searchQuery.value = query
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Load available folders from backend. */
  async function loadFolders(): Promise<void> {
    try {
      folders.value = await api.getNoteFolders()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Set the active folder filter and reload notes. */
  async function setFolder(folder: string | null): Promise<void> {
    activeFolder.value = folder
    await loadNotes()
  }

  /** Toggle a tag in the active filter and reload notes. */
  async function toggleTag(tag: string): Promise<void> {
    const idx = activeTags.value.indexOf(tag)
    if (idx === -1) {
      activeTags.value.push(tag)
    } else {
      activeTags.value.splice(idx, 1)
    }
    await loadNotes()
  }

  /** Clear the current note selection. */
  function clearCurrentNote(): void {
    currentNote.value = null
  }

  /** Clear search and reload all notes. */
  async function clearSearch(): Promise<void> {
    searchQuery.value = ''
    await loadNotes()
  }

  /** Toggle between list and graph view modes. */
  function setViewMode(mode: 'list' | 'graph'): void {
    viewMode.value = mode
  }

  return {
    notes,
    allNotes,
    total,
    currentNote,
    folders,
    activeFolder,
    activeTags,
    searchQuery,
    loading,
    saving,
    error,
    viewMode,
    allTags,
    backlinks,
    loadAllNotes,
    loadNotes,
    loadNote,
    createNote,
    createNoteInFolder,
    updateNote,
    deleteNote,
    deleteFolder,
    searchNotes,
    loadFolders,
    setFolder,
    toggleTag,
    clearCurrentNote,
    clearSearch,
    setViewMode,
  }
})
