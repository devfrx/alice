/** Workspace-scope endpoints (`/api/scope`). */
import { request } from './http'
import type { ScopeResponse } from '../../types/scope'

export const scopeApi = {
  /** Fetch the persisted workspace scope (folders + idle flag) for a conversation. */
  getScope: (conversationId: string): Promise<ScopeResponse> =>
    request<ScopeResponse>(`/scope/${encodeURIComponent(conversationId)}`),

  /**
   * Replace the workspace scope folders for a conversation.
   *
   * Idle-guarded server-side: throws {@link ApiError} with `status === 409`
   * (detail `"scope_locked"`) when a turn is running for the conversation.
   */
  setScope: (conversationId: string, folders: string[]): Promise<ScopeResponse> =>
    request<ScopeResponse>(`/scope/${encodeURIComponent(conversationId)}`, {
      method: 'PUT',
      body: JSON.stringify({ folders }),
    }),

  /**
   * Clear the workspace scope for a conversation (empties the folder list).
   *
   * Idle-guarded server-side: throws {@link ApiError} with `status === 409`
   * (detail `"scope_locked"`) when a turn is running for the conversation.
   */
  clearScope: (conversationId: string): Promise<ScopeResponse> =>
    request<ScopeResponse>(`/scope/${encodeURIComponent(conversationId)}`, { method: 'DELETE' }),
}
