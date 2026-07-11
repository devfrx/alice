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

import type { ApiSchema } from './generated'

/** Generated from the backend contract — do not redefine locally. */
export type PermissionMode = ApiSchema<'PermissionMode'>
export type PermissionModeResponse = ApiSchema<'PermissionModeResponse'>

/** Generated from the backend WS contract — do not redefine locally. */
export type WsPermissionModeUpdatedMessage = ApiSchema<'WsPermissionModeUpdated'>

/**
 * The effect of a persistent permission rule (mirrors backend ``RuleEffect``).
 * Precedence at match time is ``deny`` > ``ask`` > ``allow``.
 */
export type RuleEffect = 'allow' | 'ask' | 'deny'

/**
 * Where a rule applies. ``conversation`` ties it to one conversation;
 * ``global`` applies everywhere. A null ``conversation_id`` in
 * {@link PermissionRule} denotes a global rule.
 */
export type RuleScope = 'conversation' | 'global'

/**
 * A persisted permission rule, as returned by
 * `GET/POST /api/permission-rules/{conversation_id}`.
 */
export interface PermissionRule {
  id: string
  /** Null for a global rule; otherwise the owning conversation id. */
  conversation_id: string | null
  tool_name: string
  effect: RuleEffect
}

/** Request body for `POST /api/permission-rules/{conversation_id}`. */
export interface PermissionRuleCreate {
  tool_name: string
  effect: RuleEffect
  scope: RuleScope
}
