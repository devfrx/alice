/**
 * REST API client for the OMNIA backend.
 *
 * Every method is strongly typed against the shapes defined in
 * `types/chat.ts` which mirror the backend JSON responses exactly.
 */

import type {
  ConversationDetail,
  ConversationExport,
  ConversationSummary,
  DeleteAllConversationsResponse,
  DeleteConversationResponse,
  FileAttachment,
  RenameConversationResponse
} from '../types/chat'
import type { PluginInfo } from '../types/plugin'
import type {
  DownloadStatusResponse,
  LMStudioModel,
  ModelDownloadResponse,
  ModelLoadResponse,
  ModelOperationResponse,
  ModelUnloadResponse,
  ModelsStatusResponse
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

/** Backend host (without /api), configurable via VITE_API_BASE_URL env var. */
const BACKEND_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

/** Base URL for all REST calls. */
const BASE_URL = `${BACKEND_BASE}/api`

/** Backend host root (without /api), used to resolve relative asset URLs. */
export const BACKEND_HOST = BACKEND_BASE

/**
 * Resolve a backend-relative path (e.g. `/uploads/...`) to an absolute URL.
 * Passes through URLs that are already absolute or blob/data URIs.
 */
export function resolveBackendUrl(path: string): string {
  if (!path) return path
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('blob:') || path.startsWith('data:')) {
    return path
  }
  return `${BACKEND_HOST}${path.startsWith('/') ? '' : '/'}${path}`
}

/**
 * Generic fetch wrapper with JSON parsing and error handling.
 *
 * @typeParam T - Expected response body type.
 * @param endpoint - Path appended to {@link BASE_URL} (must start with `/`).
 * @param options  - Standard `RequestInit` overrides.
 * @returns Parsed JSON body cast to `T`.
 * @throws {Error} On non-2xx status codes.
 */
async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const { headers: customHeaders, ...fetchOptions } = options ?? {}
  const hasBody = !!fetchOptions.body
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...fetchOptions,
    headers: {
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
      ...(customHeaders as Record<string, string>)
    }
  })

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

}
