/**
 * tasks.ts — Canonical Tasks (todo-list) types aligned with the AL\CE backend.
 *
 * The model-driven turn engine maintains a per-conversation task list via the
 * `update_plan` meta-tool; the backend persists it and exposes it two ways:
 *
 * - REST snapshot: `GET /api/tasks/{conversation_id}` → {@link TasksResponse}.
 * - Live push on the events WebSocket: a {@link WsTasksUpdatedMessage} frame
 *   carrying the FULL step list, folded directly into the `tasks` Pinia store
 *   (no re-fetch required).
 *
 * A {@link TaskStep} mirrors the backend step dict `{ "step", "status" }`.
 */

import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type TaskStep = ApiSchema<'WsTaskStep'>
export type WsTasksUpdatedMessage = ApiSchema<'WsTasksUpdated'>

/** REST payload returned by `GET /api/tasks/{conversation_id}`. */
export interface TasksResponse {
  conversation_id: string
  steps: TaskStep[]
}
