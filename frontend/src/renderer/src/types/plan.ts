/**
 * plan.ts — Canonical Plan (todo-list) types aligned with the AL\CE backend.
 *
 * The model-driven turn engine maintains a per-conversation plan via the
 * `update_plan` meta-tool; the backend persists it (see `PlanService`) and
 * exposes it two ways:
 *
 * - REST snapshot: `GET /api/plans/{conversation_id}` → {@link PlanResponse}.
 * - Live push on the events WebSocket: a {@link WsPlanUpdatedMessage} frame
 *   carrying the FULL step list, folded directly into the `plan` Pinia store
 *   (no re-fetch required).
 *
 * A {@link PlanStep} mirrors the backend step dict `{ "step", "status" }`.
 */

/** One ordered step of a conversation plan. */
export interface PlanStep {
  /** Human-readable description of the step. */
  step: string
  /** Lifecycle state: "pending" | "in_progress" | "completed". */
  status: string
}

/** REST payload returned by `GET /api/plans/{conversation_id}`. */
export interface PlanResponse {
  conversation_id: string
  steps: PlanStep[]
}

/** Events-WS frame pushing the full, current plan for a conversation. */
export interface WsPlanUpdatedMessage {
  type: 'plan.updated'
  conversation_id: string
  steps: PlanStep[]
}
