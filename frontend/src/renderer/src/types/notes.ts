/** A single note in the vault. Mirrors backend NoteEntry. */
export interface Note {
  id: string
  title: string
  content: string
  folder_path: string
  tags: string[]
  wikilinks: string[]
  pinned: boolean
  created_at: string
  updated_at: string
}

export interface NoteFolder {
  path: string
  count: number
}

export interface NoteListResponse {
  notes: Note[]
  total: number
}

export interface NoteSearchResult extends Note {
  score: number
}

export interface NoteSearchResponse {
  results: NoteSearchResult[]
}

export interface CreateNoteRequest {
  title: string
  content: string
  folder_path?: string
  tags?: string[]
}

export interface UpdateNoteRequest {
  title?: string
  content?: string
  folder_path?: string
  tags?: string[]
  pinned?: boolean
}
