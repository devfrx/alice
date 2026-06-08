/**
 * permission.ts — Canonical permission-tier types aligned with the AL\CE
 * backend (Fase 7).
 *
 * A conversation's *permission mode* is the authorization tier governing every
 * tool-call the agent makes. It is set ONLY by the user (never the model) and
 * the backend exposes it:
 *
 * - REST snapshot:  `GET /api/permission-mode/{conversation_id}`.
 * - REST mutation:  `PUT /api/permission-mode/{conversation_id}` — NOT
 *   idle-guarded (the engine reads the tier per tool-call, so a mid-turn change
 *   is sound).
 * - Live push on the events WebSocket: a {@link WsPermissionModeUpdatedMessage}
 *   frame folded directly into the `permissionMode` Pinia store.
 */

/** The four authorization tiers (mirrors backend ``PermissionMode``). */
export type PermissionMode = 'strict' | 'auto_edits' | 'plan' | 'autopilot'

/** REST payload returned by `GET` / `PUT /api/permission-mode/{conversation_id}`. */
export interface PermissionModeResponse {
  conversation_id: string
  mode: PermissionMode
}

/** Events-WS frame pushing the current tier for a conversation. */
export interface WsPermissionModeUpdatedMessage {
  type: 'permission_mode.updated'
  conversation_id: string
  mode: PermissionMode
}
