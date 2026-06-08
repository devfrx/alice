# Fase 3 — Design notes (canonical turn-event stream + run UI)

Companion to `PLAN.md` → "Fase 3". Records the concrete design decisions so the
phase is reviewable and resume-safe. Foundation phase ⇒ **behavior-preserving,
sequential**; the documented 93-test subset stays green throughout.

## The fork, and the decision

PLAN says: define a canonical turn-event vocabulary in
`backend/services/turn/events.py`, "normalize the existing `tool_execution_*`
behind these names", rebuild the frontend activity UI on the new events, and
remove the structured refs. §7 also says **behavior-preserving** for the
foundation phases.

A strict *rename* of the live `tool_execution_*` frames would ripple into the
93-test green bar, the live in-chat `ToolExecutionIndicator`, and the FE
stale-generation guard all at once — high blast radius for a "no observable
change" phase. So we take the **additive-then-migrate** path:

- **Stage 1 (backend):** add `events.py` (canonical vocabulary + pure builder
  functions). The engine emits the canonical events **additively**, at the same
  sites as the existing frames — the legacy frames (`token`, `thinking`,
  `tool_execution_start/done`, `tool_progress`, `llm_requery`, `done`, `error`,
  `context_*`) are **left exactly as they are**. ⇒ existing tests + live chat
  rendering are untouched; the green bar holds by construction. New backend test
  asserts the canonical events appear in a `RecordingEventSink` (additive
  assertions only).
- **Stage 2 (frontend):** new `stores/agentRun.ts` (setup-store, mirrors
  `stores/artifacts.ts`) consumes **only** the canonical events and drives a
  clean activity component (timeline of steps/tools + step/token budget). The
  **dead** `agent.*` handlers and orphaned components
  (`useAgentRun`, `useAgentActivity`, `AgentActivitySidebar`, `AgentRunSummary`,
  legacy `AgentPlanCard`, the `AgentEvent` union in `types/agent.ts`, the
  `ui.ts` agent-sidebar state) are removed — pure dead-code deletion (the
  backend emits none of `agent.run_*`/`agent.step_*`), hence behavior-preserving.
  The existing `ToolExecutionIndicator` (legacy `tool_execution_*`) stays as-is.
- **Stage 3 (deferred, NOT in Fase 3):** migrate the in-chat indicator onto the
  canonical names and drop the legacy `tool_execution_*` emission. Deferred to
  keep Fase 3 strictly behavior-preserving.

Net deviation from a pure rename: the legacy `tool_execution_*` frames keep
being emitted for now (dual emit at the tool sites). Documented, contained,
cleaned up later.

## Canonical event vocabulary (sink frames; JSON dicts with a `type` key)

`turn_id: str` (a `uuid4().hex`, minted at turn start) correlates every event of
one turn. Optional keys are **omitted** when None (tight frames).

| `type` | payload keys |
|---|---|
| `turn.started` | `turn_id, conversation_id` |
| `turn.llm_step` | `turn_id, step` (int, 0-based; initial stream = 0, each re-query +1) |
| `tool.call` | `turn_id, execution_id, tool_name, args` |
| `tool.result` | `turn_id, execution_id, tool_name, success, result` (+ `content_type?`, `artifact_id?`) |
| `interaction.requested` | `turn_id, execution_id, kind` (+ `tool_name?`) — kind ∈ `tool_confirmation`/`client_tool_call`/`ask_user` |
| `interaction.resolved` | `turn_id, execution_id, kind, outcome` — outcome ∈ `approved`/`rejected`/`answered`/`executed`/`timeout`/`cancelled`/`disconnected` |
| `turn.usage` | `turn_id, step, input_tokens, output_tokens, tool_calls, max_steps` |
| `turn.finished` | `turn_id, finish_reason, input_tokens, output_tokens, steps` |
| `plan.updated` | `turn_id, conversation_id, steps` (list of `{step, status}`) — emitted by `update_plan` in **Fase 5**; the type is defined here in Fase 3 |

`events.py` exposes: a `TurnEventType` `StrEnum` (or module string constants), a
`CANONICAL_TURN_EVENT_TYPES: frozenset[str]`, and one pure builder per event
returning the dict. Builders are keyword-only, fully type-hinted, no side
effects (trivially unit-testable). `plan.updated` is correlated by `turn_id`
when emitted inside a turn; when emitted by a standalone `update_plan` outside a
turn it may carry `turn_id=""`.

## turn_id threading

`turn_id` is minted in `DirectTurnExecutor.execute` (the turn entrypoint),
emitted with `turn.started`, and passed into `run_tool_loop(...)` as a new
**default-valued kwarg** (`turn_id: str | None = None`; the engine mints one if
absent). Default-valued ⇒ the direct `run_tool_loop` callers in
`test_tool_loop.py` / `test_confirmation_toggle.py` stay green unchanged.

## Optional `turn_run` aggregate (PLAN: "opzionalmente persistito")

A single `turn_run` table mirroring the existing `AgentRun` shape
(`db/models.py`), written at turn start/finish for timeline/audit. Kept **small
and optional**; created by `SQLModel.metadata.create_all` like the others. This
replaces the dead `AgentRun` model conceptually but we do **not** delete
`AgentRun` in this phase (out of scope; it is inert).

## Plan re-inject (seam now, wiring in Fase 5)

PLAN: at turn start the engine loads the persisted plan and injects
`render_plan` into the context so the model continues instead of re-planning.
`PlanService` lands in **Fase 5**, so Fase 3 only leaves the **seam**: the
engine has a clearly-marked hook (a no-op when no plan provider is wired). Fase 5
supplies the provider and emits `plan.updated`.

## Contract consistency

New TS types mirror the snake_case frames (one `Ws…`/event interface each,
discriminated by `type`); the `agentRun` store applies them keyed by `turn_id`
(bypassing the stale-generation guard, like the old agent handlers did). No REST
shape changes in this phase.
