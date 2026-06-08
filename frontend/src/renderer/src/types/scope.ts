/**
 * scope.ts — Canonical Workspace Scope types aligned with the AL\CE backend.
 *
 * A conversation's *scope* is the set of filesystem folders the scoped
 * Terminal plugin is confined to. The backend persists it (see `ScopeService`)
 * and exposes it three ways:
 *
 * - REST snapshot: `GET /api/scope/{conversation_id}` → {@link ScopeResponse}.
 * - REST mutation: `PUT` / `DELETE /api/scope/{conversation_id}` →
 *   {@link ScopeResponse}. Both are idle-guarded: a mutation attempted while a
 *   turn is running for that conversation returns HTTP 409 with detail
 *   `"scope_locked"`.
 * - Live push on the events WebSocket: a {@link WsScopeUpdatedMessage} frame
 *   carrying the FULL folder list, folded directly into the `scope` Pinia store
 *   (no re-fetch required). The frame omits `is_idle`.
 */

/** REST payload returned by `GET` / `PUT` / `DELETE /api/scope/{conversation_id}`. */
export interface ScopeResponse {
  conversation_id: string
  folders: string[]
  is_idle: boolean
}

/** Events-WS frame pushing the full, current folder scope for a conversation. */
export interface WsScopeUpdatedMessage {
  type: 'scope.updated'
  conversation_id: string
  folders: string[]
}
