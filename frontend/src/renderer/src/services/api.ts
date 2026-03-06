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

/** Base URL for all REST calls. */
const BASE_URL = 'http://localhost:8000/api'

/** Backend host root (without /api), used to resolve relative asset URLs. */
export const BACKEND_HOST = 'http://localhost:8000'

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
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...fetchOptions,
    headers: {
      'Content-Type': 'application/json',
      ...(customHeaders as Record<string, string>)
    }
  })

  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(`API Error ${response.status}: ${response.statusText} — ${body}`)
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
    request<ConversationExport>(`/chat/conversations/${id}/export`),

  /** Import a conversation from JSON. */
  importConversation: (data: ConversationExport): Promise<ConversationSummary> =>
    request<ConversationSummary>('/chat/conversations/import', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  /** Get the absolute filesystem path of a conversation's JSON file. */
  getConversationFilePath: (id: string): Promise<{ path: string }> =>
    request<{ path: string }>(`/chat/conversations/${id}/file-path`),

  /** Fetch a single conversation with its full message list. */
  getConversation: (id: string): Promise<ConversationDetail> =>
    request<ConversationDetail>(`/chat/conversations/${id}`),

  /** Delete a conversation and all its messages. */
  deleteConversation: (id: string): Promise<DeleteConversationResponse> =>
    request<DeleteConversationResponse>(`/chat/conversations/${id}`, { method: 'DELETE' }),

  /** Delete ALL conversations, messages, and files. */
  deleteAllConversations: (): Promise<DeleteAllConversationsResponse> =>
    request<DeleteAllConversationsResponse>('/chat/conversations', { method: 'DELETE' }),

  /** Rename a conversation. */
  renameConversation: (id: string, title: string): Promise<RenameConversationResponse> =>
    request<RenameConversationResponse>(`/chat/conversations/${id}/title`, {
      method: 'POST',
      body: JSON.stringify({ title })
    }),

  // -- Config ---------------------------------------------------------------

  /** Retrieve the list of available LLM models. */
  getModels: (): Promise<LMStudioModel[]> =>
    request<LMStudioModel[]>('/config/models'),

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
    request<PluginInfo>(`/plugins/${name}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled })
    })
}
