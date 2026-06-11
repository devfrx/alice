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

import type { ApiSchema } from './generated'

/** Generated from the backend contract — do not redefine locally. */
export type ScopeResponse = ApiSchema<'ScopeResponse'>

/** Generated from the backend WS contract — do not redefine locally. */
export type WsScopeUpdatedMessage = ApiSchema<'WsScopeUpdated'>
