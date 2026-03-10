/** Audit-related types for the OMNIA backend audit API. */

/** A single tool confirmation audit entry. */
export interface AuditConfirmationEntry {
  id: string
  conversation_id: string
  execution_id: string
  tool_name: string
  args_json: string
  risk_level: 'safe' | 'low' | 'medium' | 'dangerous' | 'forbidden'
  user_approved: boolean
  rejection_reason: string | null
  thinking_content: string | null
  created_at: string
}

/** Paginated response from GET /api/audit/confirmations. */
export interface AuditConfirmationsResponse {
  entries: AuditConfirmationEntry[]
  count: number
  offset: number
  limit: number
}
