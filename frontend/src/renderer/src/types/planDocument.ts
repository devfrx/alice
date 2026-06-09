/**
 * planDocument.ts — Canonical Plan-document types aligned with the AL\CE backend.
 *
 * Distinct from the `tasks` todo-list: the plan *document* is a free-form
 * Markdown write-up of the conversation's plan, maintained server-side and
 * exposed two ways:
 *
 * - REST snapshot: `GET /api/plan-document/{conversation_id}` →
 *   {@link PlanDocumentResponse}.
 * - Live push on the events WebSocket: a {@link WsPlanDocumentUpdatedMessage}
 *   frame carrying the full document, folded directly into the `planDocument`
 *   Pinia store (no re-fetch required).
 */

/** Client-side view-model of a conversation's plan document. */
export interface PlanDocument {
  /** Display title of the plan document. */
  title: string
  /** Markdown body of the plan document. */
  body: string
  /** ISO timestamp of the last update, or `null` when never updated. */
  updatedAt: string | null
}

/** REST payload returned by `GET /api/plan-document/{conversation_id}`. */
export interface PlanDocumentResponse {
  conversation_id: string
  title: string
  body: string
  updated_at: string | null
}

/** Events-WS frame pushing the full, current plan document for a conversation. */
export interface WsPlanDocumentUpdatedMessage {
  type: 'plan_document.updated'
  conversation_id: string
  title: string
  body: string
  updated_at: string | null
}
