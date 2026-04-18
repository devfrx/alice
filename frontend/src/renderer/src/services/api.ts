/**
 * REST API client for the AL\CE backend.
 *
 * Every method is strongly typed against the shapes defined in
 * `types/chat.ts` which mirror the backend JSON responses exactly.
 */

import type {
  BranchConversationRequest,
  BranchConversationResponse,
  ConversationDetail,
  ConversationExport,
  ConversationSummary,
  DeleteAllConversationsResponse,
  DeleteConversationResponse,
  FileAttachment,
  RenameConversationResponse,
  SwitchVersionResponse
} from '../types/chat'
import type { PluginInfo } from '../types/plugin'
import type {
  DownloadStatusResponse,
  LMStudioModel,
  ModelDownloadResponse,
  ModelLoadResponse,
  ModelOperationResponse,
  ModelUnloadResponse,
  ModelsStatusResponse,
  VectorStoreStats
} from '../types/settings'
import type { CalendarEvent, TodaySummary } from '../types/calendar'
import type { AuditConfirmationsResponse } from '../types/audit'
import type {
  MemoryListResponse,
  MemorySearchResponse,
  MemoryStats
} from '../types/memory'
import type { McpReconnectResponse, McpServersResponse } from '../types/mcp'
import type {
  AddObservationsPayload,
  CreateEntitiesPayload,
  CreateRelationsPayload,
  DeleteEntitiesPayload,
  DeleteObservationsPayload,
  DeleteRelationsPayload,
  KGGraph
} from '../types/mcpMemory'
import type {
  Note,
  NoteListResponse,
  NoteSearchResponse,
  NoteFolder,
  CreateNoteRequest,
  UpdateNoteRequest
} from '../types/notes'
import type { EmailHeader, EmailDetail, EmailSearchRequest } from '../types/email'
import type {
  WhiteboardSpec,
  WhiteboardListResponse,
  WhiteboardSnapshotUpdateResponse
} from '../types/whiteboard'

/** Backend host (without /api), configurable via VITE_API_BASE_URL env var. */
const BACKEND_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

/** Base URL for all REST calls. */
const BASE_URL = `${BACKEND_BASE}/api`

/** Backend host root (without /api), used to resolve relative asset URLs. */
export const BACKEND_HOST = BACKEND_BASE

/**
 * Resolve a backend-relative path (e.g. `/uploads/...`) to an absolute URL.
 * Passes through URLs that are already absolute or blob/data URIs.
 * Rejects any path containing URL-encoded traversal sequences.
 */
export function resolveBackendUrl(path: string): string {
  if (!path) return path
  if (
    path.startsWith('http://') ||
    path.startsWith('https://') ||
    path.startsWith('blob:') ||
    path.startsWith('data:')
  ) {
    // Only allow absolute URLs pointing to the known backend host.
    if (path.startsWith('http://') || path.startsWith('https://')) {
      try {
        const url = new URL(path)
        const backend = new URL(BACKEND_HOST)
        if (url.origin !== backend.origin) {
          console.warn('[resolveBackendUrl] Rejected external URL:', path)
          return ''
        }
      } catch {
        return ''
      }
    }
    return path
  }
  // Reject path traversal attempts
  if (path.includes('..')) {
    console.warn('[resolveBackendUrl] Rejected path traversal:', path)
    return ''
  }
  return `${BACKEND_HOST}${path.startsWith('/') ? '' : '/'}${path}`
}

/** Default HTTP request timeout (ms). Long enough for slow LLM/model endpoints. */
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000

/**
 * Compose an external AbortSignal with an internal timeout signal.
 * Returns the combined signal plus a cleanup function that clears the timer.
 */
function withTimeout(
  external: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; cleanup: () => void } {
  const ctrl = new AbortController()
  const onAbort = (): void => { ctrl.abort((external as AbortSignal & { reason?: unknown }).reason) }
  if (external) {
    if (external.aborted) ctrl.abort((external as AbortSignal & { reason?: unknown }).reason)
    else external.addEventListener('abort', onAbort, { once: true })
  }
  const timer = setTimeout(() => ctrl.abort(new DOMException('Request timeout', 'TimeoutError')), timeoutMs)
  return {
    signal: ctrl.signal,
    cleanup: () => {
      clearTimeout(timer)
      external?.removeEventListener('abort', onAbort)
    },
  }
}

/**
 * Generic fetch wrapper with JSON parsing, timeout and error handling.
 *
 * @typeParam T - Expected response body type.
 * @param endpoint - Path appended to {@link BASE_URL} (must start with `/`).
 * @param options  - Standard `RequestInit` overrides; pass `signal` for cancellation.
 * @param timeoutMs - Per-request timeout in ms (default {@link DEFAULT_REQUEST_TIMEOUT_MS}).
 * @returns Parsed JSON body cast to `T`.
 * @throws {Error} On non-2xx status codes, network failure, timeout, or abort.
 */
async function request<T>(
  endpoint: string,
  options?: RequestInit,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const { headers: customHeaders, signal: externalSignal, ...fetchOptions } = options ?? {}
  const isJsonBody = !!fetchOptions.body && typeof fetchOptions.body === 'string'
  const { signal, cleanup } = withTimeout(externalSignal ?? undefined, timeoutMs)
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${endpoint}`, {
      ...fetchOptions,
      signal,
      headers: {
        ...(isJsonBody ? { 'Content-Type': 'application/json' } : {}),
        ...(customHeaders as Record<string, string>)
      }
    })
  } finally {
    cleanup()
  }

  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(`API Error ${response.status}: ${response.statusText} — ${body}`)
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }

  return response.json()
}

// ---------------------------------------------------------------------------
// Backend readiness gate
// ---------------------------------------------------------------------------

/**
 * Poll the backend health endpoint until it responds, then resolve.
 * Used at startup to gate all API/WS connections until the server is up.
 *
 * @param intervalMs - Polling interval in milliseconds (default 1 s).
 * @param signal - Optional AbortSignal for cancellation.
 * @returns `true` once the backend is reachable.
 */
export async function waitForBackend(
  intervalMs = 1000,
  signal?: AbortSignal,
): Promise<boolean> {
  while (!signal?.aborted) {
    try {
      const res = await fetch(`${BASE_URL}/health`, { signal })
      if (res.ok) return true
    } catch {
      // Backend not up yet — continue polling
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, intervalMs)
      signal?.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
    })
  }
  return false
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  // -- Chat conversations ---------------------------------------------------

  /** List all conversations (most recent first). */
  getConversations: (): Promise<ConversationSummary[]> =>
    request<ConversationSummary[]>('/chat/conversations'),

  /** Create a new empty conversation on the backend. */
  createConversation: (id: string, title?: string): Promise<ConversationSummary> =>
    request<ConversationSummary>('/chat/conversations', {
      method: 'POST',
      body: JSON.stringify({ id, title: title ?? null })
    }),

  /** Export a conversation as JSON. */
  exportConversation: (id: string): Promise<ConversationExport> =>
    request<ConversationExport>(`/chat/conversations/${encodeURIComponent(id)}/export`),

  /** Import a conversation from JSON. */
  importConversation: (data: ConversationExport): Promise<ConversationSummary> =>
    request<ConversationSummary>('/chat/conversations/import', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  /** Get the absolute filesystem path of a conversation's JSON file. */
  getConversationFilePath: (id: string): Promise<{ path: string }> =>
    request<{ path: string }>(`/chat/conversations/${encodeURIComponent(id)}/file-path`),

  /** Fetch a single conversation with its full message list. */
  getConversation: (id: string): Promise<ConversationDetail> =>
    request<ConversationDetail>(`/chat/conversations/${encodeURIComponent(id)}`),

  /** Delete a conversation and all its messages. */
  deleteConversation: (id: string): Promise<DeleteConversationResponse> =>
    request<DeleteConversationResponse>(`/chat/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** Delete ALL conversations, messages, and files. */
  deleteAllConversations: (): Promise<DeleteAllConversationsResponse> =>
    request<DeleteAllConversationsResponse>('/chat/conversations', { method: 'DELETE' }),

  /** Rename a conversation. */
  renameConversation: (id: string, title: string): Promise<RenameConversationResponse> =>
    request<RenameConversationResponse>(`/chat/conversations/${encodeURIComponent(id)}/title`, {
      method: 'POST',
      body: JSON.stringify({ title })
    }),

  /** Switch the active version for a message version group. */
  switchVersion: (
    conversationId: string,
    versionGroupId: string,
    versionIndex: number
  ): Promise<SwitchVersionResponse> =>
    request<SwitchVersionResponse>(
      `/chat/conversations/${encodeURIComponent(conversationId)}/switch-version`,
      {
        method: 'POST',
        body: JSON.stringify({
          version_group_id: versionGroupId,
          version_index: versionIndex
        })
      }
    ),

  /**
   * Branch a conversation from a specific message.
   *
   * Creates a new conversation containing all messages from the start
   * of {@link conversationId} up through {@link fromMessageId} (inclusive,
   * following the active version branch).
   *
   * @param conversationId - Source conversation UUID.
   * @param fromMessageId - UUID of the last message to copy (inclusive).
   * @param title - Optional title override for the new conversation.
   * @returns Metadata for the newly created conversation.
   */
  branchConversation: (
    conversationId: string,
    fromMessageId: string,
    title?: string,
  ): Promise<BranchConversationResponse> => {
    const body: BranchConversationRequest = { from_message_id: fromMessageId }
    if (title) body.title = title
    return request<BranchConversationResponse>(
      `/chat/conversations/${encodeURIComponent(conversationId)}/branch`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      }
    )
  },

  // -- Config ---------------------------------------------------------------

  /** Retrieve the list of available LLM models (via /config/models). */
  getModels: (): Promise<LMStudioModel[]> =>
    request<LMStudioModel[]>('/config/models'),

  /** Retrieve the list of available LLM models (via /models). */
  listModels: (): Promise<LMStudioModel[]> =>
    request<LMStudioModel[]>('/models'),

  /** Load a model into LM Studio. */
  loadModel: (
    model: string,
    config?: { context_length?: number; flash_attention?: boolean }
  ): Promise<ModelLoadResponse> =>
    request<ModelLoadResponse>('/models/load', {
      method: 'POST',
      body: JSON.stringify({ model, ...config })
    }),

  /** Unload a model instance from LM Studio. */
  unloadModel: (instanceId: string): Promise<ModelUnloadResponse> =>
    request<ModelUnloadResponse>('/models/unload', {
      method: 'POST',
      body: JSON.stringify({ instance_id: instanceId })
    }),

  /** Start downloading a model. */
  downloadModel: (model: string, quantization?: string): Promise<ModelDownloadResponse> =>
    request<ModelDownloadResponse>('/models/download', {
      method: 'POST',
      body: JSON.stringify({ model, ...(quantization ? { quantization } : {}) })
    }),

  /** Get download job status. */
  getDownloadStatus: (jobId: string): Promise<DownloadStatusResponse> =>
    request<DownloadStatusResponse>(`/models/download/${encodeURIComponent(jobId)}`),

  /** Get quick LM Studio connection status + model summary. */
  getModelsStatus: (): Promise<ModelsStatusResponse> =>
    request<ModelsStatusResponse>('/models/status'),

  /** Get current model operation status. */
  getModelOperation: (): Promise<ModelOperationResponse> =>
    request<ModelOperationResponse>('/models/operation'),

  /** Retrieve the current server configuration. */
  getConfig: (): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/config'),

  /** Update the server configuration. */
  updateConfig: (config: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/config', {
      method: 'PUT',
      body: JSON.stringify(config)
    }),

  // -- File uploads ---------------------------------------------------------

  /**
   * Upload a file attachment for a conversation.
   *
   * @param file           - The `File` object to upload.
   * @param conversationId - Target conversation ID.
   * @returns The created {@link FileAttachment} metadata.
   */
  uploadFile: async (file: File, conversationId: string): Promise<FileAttachment> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('conversation_id', conversationId)
    const response = await fetch(`${BASE_URL}/chat/upload`, {
      method: 'POST',
      body: formData
    })
    if (!response.ok) {
      const body = await response.text().catch(() => '')
      throw new Error(`Upload failed ${response.status}: ${body}`)
    }
    const data: FileAttachment = await response.json()
    // Resolve relative URL to absolute backend URL so images load in Electron.
    data.url = resolveBackendUrl(data.url)
    return data
  },

  // -- Model sync -----------------------------------------------------------

  /** Sync config with the model currently loaded in LM Studio. */
  syncModel: (): Promise<{ synced: boolean; model?: string; reason?: string }> =>
    request<{ synced: boolean; model?: string; reason?: string }>('/config/sync-model', {
      method: 'POST'
    }),

  // -- Plugins --------------------------------------------------------------

  /** List installed plugins. */
  getPlugins: (): Promise<PluginInfo[]> => request<PluginInfo[]>('/plugins'),

  /** Enable or disable a plugin by name. */
  togglePlugin: (name: string, enabled: boolean): Promise<PluginInfo> =>
    request<PluginInfo>(`/plugins/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled })
    }),

  // -- Voice ----------------------------------------------------------------

  /** Get voice service status (STT/TTS availability). */
  getVoiceStatus: (): Promise<{ stt_available: boolean; tts_available: boolean; active_connections: number }> =>
    request<{ stt_available: boolean; tts_available: boolean; active_connections: number }>('/voice/status'),

  // -- Settings -------------------------------------------------------------

  /** Toggle tool confirmations on/off. */
  setToolConfirmations: (enabled: boolean): Promise<{ confirmations_enabled: boolean }> =>
    request<{ confirmations_enabled: boolean }>('/settings/tool-confirmations', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current tool confirmations state from backend. */
  getToolConfirmations: (): Promise<{ confirmations_enabled: boolean }> =>
    request<{ confirmations_enabled: boolean }>('/settings/tool-confirmations'),

  /** Toggle system prompt on/off. */
  setSystemPrompt: (enabled: boolean): Promise<{ system_prompt_enabled: boolean }> =>
    request<{ system_prompt_enabled: boolean }>('/settings/system-prompt', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current system prompt enabled state from backend. */
  getSystemPrompt: (): Promise<{ system_prompt_enabled: boolean }> =>
    request<{ system_prompt_enabled: boolean }>('/settings/system-prompt'),

  /** Toggle tools on/off. */
  setTools: (enabled: boolean): Promise<{ tools_enabled: boolean }> =>
    request<{ tools_enabled: boolean }>('/settings/tools', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current tools enabled state from backend. */
  getTools: (): Promise<{ tools_enabled: boolean }> =>
    request<{ tools_enabled: boolean }>('/settings/tools'),

  /** Get all persisted user preferences. */
  getPreferences: (): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/settings/preferences'),

  /** Reset all persisted preferences to defaults. */
  resetPreferences: (): Promise<{ deleted: number; message: string }> =>
    request<{ deleted: number; message: string }>('/settings/preferences', { method: 'DELETE' }),

  /** Probe which TTS/STT engine libraries are installed on the backend. */
  getAvailableVoiceEngines: (): Promise<{
    tts: Record<string, boolean>
    stt: Record<string, boolean>
  }> =>
    request<{ tts: Record<string, boolean>; stt: Record<string, boolean> }>(
      '/settings/voice/available-engines'
    ),

  // -- Plugin tool execution ------------------------------------------------

  /** Execute a plugin tool directly via REST. */
  executePluginTool: <T = unknown>(
    plugin: string,
    tool: string,
    args: Record<string, unknown> = {}
  ): Promise<{ success: boolean; content: T; error_message?: string }> =>
    request<{ success: boolean; content: T; error_message?: string }>(
      '/plugins/execute',
      {
        method: 'POST',
        body: JSON.stringify({ plugin, tool, args })
      }
    ),

  // -- Calendar -------------------------------------------------------------

  /** Fetch today's calendar events. */
  getCalendarToday: (): Promise<TodaySummary> =>
    request<TodaySummary>('/calendar/today'),

  /** Fetch upcoming events (next N). */
  getCalendarUpcoming: (limit?: number): Promise<CalendarEvent[]> =>
    request<CalendarEvent[]>(`/calendar/upcoming${limit ? `?limit=${limit}` : ''}`),

  /** Fetch events in a date range. */
  getCalendarEvents: (startDate?: string, endDate?: string, maxResults?: number): Promise<CalendarEvent[]> => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    if (maxResults) params.set('max_results', String(maxResults))
    const qs = params.toString()
    return request<CalendarEvent[]>(`/calendar/events${qs ? `?${qs}` : ''}`)
  },

  /** Create a new calendar event. */
  createCalendarEvent: (data: {
    title: string
    start_time: string
    end_time: string
    description?: string
    reminder_minutes?: number
    recurrence_rule?: string
  }): Promise<CalendarEvent> =>
    request<CalendarEvent>('/calendar/events', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  /** Update an existing calendar event. */
  updateCalendarEvent: (id: string, data: Record<string, unknown>): Promise<CalendarEvent> =>
    request<CalendarEvent>(`/calendar/events/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  /** Delete a calendar event. */
  deleteCalendarEvent: (id: string): Promise<{ deleted: boolean; id: string }> =>
    request<{ deleted: boolean; id: string }>(`/calendar/events/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    }),

  // -- Audit ----------------------------------------------------------------

  /** List tool confirmation audit entries with optional filters. */
  getAuditConfirmations: (params?: {
    conversationId?: string
    toolName?: string
    approved?: boolean
    limit?: number
    offset?: number
  }): Promise<AuditConfirmationsResponse> => {
    const qs = new URLSearchParams()
    if (params?.conversationId) qs.set('conversation_id', params.conversationId)
    if (params?.toolName) qs.set('tool_name', params.toolName)
    if (params?.approved !== undefined) qs.set('approved', String(params.approved))
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<AuditConfirmationsResponse>(`/audit/confirmations${q ? `?${q}` : ''}`)
  },

  // -- Memory ---------------------------------------------------------------

  /** Fetch memory entries with optional filters. */
  getMemories: (params?: {
    scope?: string
    category?: string
    limit?: number
    offset?: number
  }): Promise<MemoryListResponse> => {
    const qs = new URLSearchParams()
    if (params?.scope) qs.set('scope', params.scope)
    if (params?.category) qs.set('category', params.category)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<MemoryListResponse>(`/memory${q ? `?${q}` : ''}`)
  },

  /** Semantic search over memories. */
  searchMemories: (query: string, limit = 10, category?: string): Promise<MemorySearchResponse> =>
    request<MemorySearchResponse>('/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, ...(category ? { category } : {}) })
    }),

  /** Delete a single memory entry by ID. */
  deleteMemory: (id: string): Promise<{ deleted: true }> =>
    request<{ deleted: true }>(`/memory/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** Clear all session-scoped memories. */
  clearSessionMemory: (): Promise<{ deleted_count: number }> =>
    request<{ deleted_count: number }>('/memory/session', { method: 'DELETE' }),

  /** Clear ALL memories (every scope). */
  clearAllMemory: (): Promise<{ deleted_count: number }> =>
    request<{ deleted_count: number }>('/memory/all', { method: 'DELETE' }),

  /** Load memory statistics. */
  getMemoryStats: (): Promise<MemoryStats> =>
    request<MemoryStats>('/memory/stats'),

  // -- MCP Servers ----------------------------------------------------------

  /** List all configured MCP servers with status and tools. */
  getMcpServers: (): Promise<McpServersResponse> =>
    request<McpServersResponse>('/mcp/servers'),

  /** Reconnect a specific MCP server. */
  reconnectMcpServer: (name: string): Promise<McpReconnectResponse> =>
    request<McpReconnectResponse>(`/mcp/servers/${encodeURIComponent(name)}/reconnect`, {
      method: 'POST',
    }),

  // -- MCP Memory (Knowledge Graph) ----------------------------------------

  /** Read the entire knowledge graph. */
  getKnowledgeGraph: (): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/graph'),

  /** Search the knowledge graph by query. */
  searchKnowledgeGraph: (query: string): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query }),
    }),

  /** Retrieve specific entities by name. */
  openKnowledgeNodes: (names: string[]): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/nodes', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),

  /** Create new entities. */
  createKGEntities: (payload: CreateEntitiesPayload): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/entities', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Delete entities and their relations. */
  deleteKGEntities: (payload: DeleteEntitiesPayload): Promise<unknown> =>
    request<unknown>('/mcp/memory/entities', {
      method: 'DELETE',
      body: JSON.stringify(payload),
    }),

  /** Create relations between entities. */
  createKGRelations: (payload: CreateRelationsPayload): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/relations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Delete specific relations. */
  deleteKGRelations: (payload: DeleteRelationsPayload): Promise<unknown> =>
    request<unknown>('/mcp/memory/relations', {
      method: 'DELETE',
      body: JSON.stringify(payload),
    }),

  /** Add observations to existing entities. */
  addKGObservations: (payload: AddObservationsPayload): Promise<unknown> =>
    request<unknown>('/mcp/memory/observations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Remove specific observations from entities. */
  deleteKGObservations: (payload: DeleteObservationsPayload): Promise<unknown> =>
    request<unknown>('/mcp/memory/observations', {
      method: 'DELETE',
      body: JSON.stringify(payload),
    }),

  // -- Notes ----------------------------------------------------------------

  /** Fetch notes with optional filters. */
  getNotes: (params?: {
    folder?: string
    tags?: string
    pinned?: boolean
    q?: string
    limit?: number
    offset?: number
  }): Promise<NoteListResponse> => {
    const qs = new URLSearchParams()
    if (params?.folder) qs.set('folder', params.folder)
    if (params?.tags) qs.set('tags', params.tags)
    if (params?.pinned !== undefined) qs.set('pinned', String(params.pinned))
    if (params?.q) qs.set('q', params.q)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<NoteListResponse>(`/notes${q ? `?${q}` : ''}`)
  },

  /** Fetch a single note by ID. */
  getNote: (id: string): Promise<Note> =>
    request<Note>(`/notes/${encodeURIComponent(id)}`),

  /** Create a new note. */
  createNote: (data: CreateNoteRequest): Promise<Note> =>
    request<Note>('/notes', { method: 'POST', body: JSON.stringify(data) }),

  /** Update an existing note. */
  updateNote: (id: string, data: UpdateNoteRequest): Promise<Note> =>
    request<Note>(`/notes/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  /** Delete a note by ID. */
  deleteNote: (id: string): Promise<{ deleted: boolean }> =>
    request<{ deleted: boolean }>(`/notes/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    }),

  /** Full-text search over notes. */
  searchNotes: (
    query: string,
    folder?: string,
    tags?: string[],
    limit?: number
  ): Promise<NoteSearchResponse> =>
    request<NoteSearchResponse>('/notes/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        ...(folder ? { folder } : {}),
        ...(tags ? { tags } : {}),
        ...(limit ? { limit } : {})
      })
    }),

  /** Get all note folders with counts. */
  getNoteFolders: (): Promise<NoteFolder[]> =>
    request<NoteFolder[]>('/notes/folders'),

  /** Delete a folder. mode = 'move' (notes → root) or 'delete'. */
  deleteFolder: (
    folderPath: string,
    mode: 'move' | 'delete' = 'move'
  ): Promise<{ affected: number; mode: string }> =>
    request<{ affected: number; mode: string }>('/notes/folders/delete', {
      method: 'POST',
      body: JSON.stringify({ folder_path: folderPath, mode })
    }),

  // -- Email Assistant (Phase 15) -----------------------------------------

  /** Fetch email inbox headers. */
  getEmailInbox: (params?: {
    folder?: string
    limit?: number
    unread_only?: boolean
  }): Promise<EmailHeader[]> => {
    const qs = new URLSearchParams()
    if (params?.folder) qs.set('folder', params.folder)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.unread_only !== undefined) qs.set('unread_only', String(params.unread_only))
    const q = qs.toString()
    return request<EmailHeader[]>(`/email/inbox${q ? `?${q}` : ''}`)
  },

  /** Fetch a single email's full content. */
  getEmail: (uid: string, folder = 'INBOX'): Promise<EmailDetail> =>
    request<EmailDetail>(`/email/${encodeURIComponent(uid)}?folder=${encodeURIComponent(folder)}`),

  /** Search emails using IMAP criteria. */
  searchEmails: (req: EmailSearchRequest): Promise<EmailHeader[]> =>
    request<EmailHeader[]>('/email/search', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  /** Mark email as read or unread. */
  markEmailRead: (uid: string, folder: string, read: boolean): Promise<{ success: boolean }> =>
    request<{ success: boolean }>(
      `/email/${encodeURIComponent(uid)}/read?folder=${encodeURIComponent(folder)}&read=${read}`,
      { method: 'PUT' },
    ),

  /** Archive an email. */
  archiveEmail: (uid: string, fromFolder: string): Promise<{ success: boolean }> =>
    request<{ success: boolean }>(
      `/email/${encodeURIComponent(uid)}/archive?from_folder=${encodeURIComponent(fromFolder)}`,
      { method: 'PUT' },
    ),

  /** List IMAP folders. */
  getEmailFolders: (): Promise<string[]> => request<string[]>('/email/folders'),

  // -- Whiteboards (Phase 16) ---------------------------------------------

  /** Fetch paginated whiteboard list, optionally filtered by conversation. */
  getWhiteboards: (params?: {
    conversation_id?: string
    limit?: number
    offset?: number
  }): Promise<WhiteboardListResponse> => {
    const qs = new URLSearchParams()
    if (params?.conversation_id) qs.set('conversation_id', params.conversation_id)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<WhiteboardListResponse>(`/whiteboards${q ? `?${q}` : ''}`)
  },

  /** Fetch a single whiteboard spec (including tldraw snapshot). */
  getWhiteboard: (boardId: string): Promise<WhiteboardSpec> =>
    request<WhiteboardSpec>(`/whiteboards/${encodeURIComponent(boardId)}`),

  /** Delete a whiteboard by ID. */
  deleteWhiteboard: (boardId: string): Promise<{ status: string; board_id: string }> =>
    request<{ status: string; board_id: string }>(
      `/whiteboards/${encodeURIComponent(boardId)}`,
      { method: 'DELETE' }
    ),

  /** Save the tldraw snapshot for an existing whiteboard. */
  saveWhiteboardSnapshot: (
    boardId: string,
    snapshot: Record<string, unknown>
  ): Promise<WhiteboardSnapshotUpdateResponse> =>
    request<WhiteboardSnapshotUpdateResponse>(
      `/whiteboards/${encodeURIComponent(boardId)}/snapshot`,
      { method: 'PATCH', body: JSON.stringify({ snapshot }) }
    ),

  // -- Qdrant Vector Store --------------------------------------------------

  /** Fetch Qdrant vector store statistics. */
  getVectorStoreStats: (): Promise<VectorStoreStats> =>
    request<VectorStoreStats>('/vector-store/stats'),

  /** Trigger re-embedding of all registered tools. */
  reembedTools: (): Promise<{ status: string }> =>
    request<{ status: string }>('/vector-store/reembed-tools', { method: 'POST' }),

}
