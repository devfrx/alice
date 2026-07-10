/** Tool confirmation audit endpoints (`/api/audit`). */
import { request } from './http'
import type { AuditConfirmationsResponse } from '../../types/audit'

export const auditApi = {
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
  }
}
