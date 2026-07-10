/** Permission mode + persistent rule endpoints (`/api/permission-mode`, `/api/permission-rules`). */
import { request } from './http'
import type {
  PermissionMode,
  PermissionModeResponse,
  PermissionRule,
  PermissionRuleCreate
} from '../../types/permission'

export const permissionsApi = {
  /** Fetch the permission tier for a conversation. */
  getPermissionMode: (conversationId: string): Promise<PermissionModeResponse> =>
    request<PermissionModeResponse>(`/permission-mode/${encodeURIComponent(conversationId)}`),

  /**
   * Set the permission tier for a conversation. NOT idle-guarded — the engine
   * reads the tier per tool-call, so a mid-turn change takes effect on the next
   * gated call.
   */
  setPermissionMode: (
    conversationId: string,
    mode: PermissionMode
  ): Promise<PermissionModeResponse> =>
    request<PermissionModeResponse>(`/permission-mode/${encodeURIComponent(conversationId)}`, {
      method: 'PUT',
      body: JSON.stringify({ mode })
    }),

  /**
   * List the persistent rules visible to a conversation: its own
   * conversation-scoped rules plus all global rules.
   */
  listPermissionRules: (conversationId: string): Promise<PermissionRule[]> =>
    request<PermissionRule[]>(`/permission-rules/${encodeURIComponent(conversationId)}`),

  /**
   * Add or update a persistent rule. `scope` selects whether the rule is tied
   * to this conversation or applies globally. UPSERT — one rule per
   * (scope, tool_name).
   */
  addPermissionRule: (
    conversationId: string,
    body: PermissionRuleCreate
  ): Promise<PermissionRule> =>
    request<PermissionRule>(`/permission-rules/${encodeURIComponent(conversationId)}`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),

  /** Delete a persistent rule by id (no-op if it does not exist). */
  deletePermissionRule: (conversationId: string, ruleId: string): Promise<void> =>
    request<void>(
      `/permission-rules/${encodeURIComponent(conversationId)}/${encodeURIComponent(ruleId)}`,
      { method: 'DELETE' }
    )
}
