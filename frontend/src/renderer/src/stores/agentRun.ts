/**
 * agentRun.ts — Pinia setup-store folding the canonical turn-event stream.
 *
 * Each server→client turn-event frame (see `types/turn.ts`, mirroring
 * `backend/services/turn/events.py`) is applied through an idempotent action
 * that folds it into a per-turn {@link AgentRun} view-model keyed by `turnId`.
 *
 * Frames may arrive out of order (e.g. a `tool.result` before its
 * `tool.call`, or any frame before `turn.started`), so every apply path goes
 * through {@link ensureRun}, which lazily materialises a minimal `running`
 * run rather than throwing. Reactivity is preserved by reassigning the
 * `runs` record / `tools` arrays (new objects) and mutating run fields through
 * the reactive proxy returned by {@link ensureRun}.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { AskUserRequest, ConfirmationRequest } from '../types/chat'
import type {
  AgentRun,
  InteractionActivity,
  ToolActivity,
  WsInteractionRequestedMessage,
  WsInteractionResolvedMessage,
  WsToolCallMessage,
  WsToolProgressMessage,
  WsToolResultMessage,
  WsToolStartedMessage,
  WsTurnFinishedMessage,
  WsTurnLlmStepMessage,
  WsTurnStartedMessage,
  WsTurnUsageMessage
} from '../types/turn'

/**
 * Stable frozen sentinel used by {@link currentRun} while `pendingTurn` is
 * active — covers the gap between the user hitting send and `turn.started`
 * arriving so the reasoning thread shows a clean "starting" state instead of
 * the previous finished run.
 */
const PENDING_RUN: AgentRun = Object.freeze({
  turnId: '__pending__',
  conversationId: '',
  status: 'running',
  step: 0,
  maxSteps: 0,
  tools: [],
  interactions: [],
  inputTokens: 0,
  outputTokens: 0,
  toolCalls: 0,
  finishReason: null,
  cost: null
}) as AgentRun

export const useAgentRunStore = defineStore('agentRun', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** All agent runs known to the client, keyed by `turnId`. */
  const runs = ref<Record<string, AgentRun>>({})

  /** Turn id of the most recently started run (drives {@link currentRun}). */
  const currentTurnId = ref<string | null>(null)

  /**
   * When true, {@link currentRun} returns {@link PENDING_RUN} — a fresh
   * zero-state "running" sentinel that covers the send → `turn.started` gap.
   * Cleared on the first `turn.started` that arrives.
   */
  const pendingTurn = ref(false)

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** The run for {@link currentTurnId}, or null when none is active. */
  const currentRun = computed<AgentRun | null>(() => {
    if (pendingTurn.value) return PENDING_RUN
    return currentTurnId.value ? (runs.value[currentTurnId.value] ?? null) : null
  })

  /** Lookup helper: the run for a given turn id, if known. */
  function runByTurnId(id: string): AgentRun | null {
    return runs.value[id] ?? null
  }

  /**
   * Pending tool confirmations of the current run, projected into the dialog
   * view-model ({@link ConfirmationRequest}). The canonical fold (spec §5):
   * the dialog reads its state from `agentRun`, keyed by `interactionId`.
   */
  const pendingConfirmations = computed<ConfirmationRequest[]>(() => {
    const run = currentRun.value
    if (!run) return []
    return run.interactions
      .filter((i) => i.status === 'pending' && i.kind === 'tool_confirmation')
      .map((i) => ({
        interactionId: i.interactionId,
        executionId: i.executionId,
        toolName: i.toolName ?? '',
        args: i.args ?? {},
        riskLevel: (i.riskLevel ?? 'medium') as ConfirmationRequest['riskLevel'],
        description: i.description ?? '',
        reasoning: i.reasoning ?? undefined,
        allowRemember: i.allowRemember ?? undefined,
        toolMeta: i.toolMeta
      }))
  })

  /**
   * Pending `ask_user` requests of the current run, projected into the
   * inline-wizard view-model ({@link AskUserRequest}).
   */
  const pendingAskUser = computed<AskUserRequest[]>(() => {
    const run = currentRun.value
    if (!run) return []
    return run.interactions
      .filter((i) => i.status === 'pending' && i.kind === 'ask_user')
      .map((i) => ({
        interactionId: i.interactionId,
        executionId: i.executionId,
        questions: i.questions ?? []
      }))
  })

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  /**
   * Return the existing run for `turnId`, lazily creating a minimal
   * `running` run when absent so out-of-order frames never throw.
   *
   * Always returns the reactive proxy stored in {@link runs}, so callers
   * can mutate run fields in place and have the change tracked.
   */
  function ensureRun(turnId: string, conversationId?: string): AgentRun {
    const existing = runs.value[turnId]
    if (existing) return existing
    const run: AgentRun = {
      turnId,
      conversationId: conversationId ?? '',
      status: 'running',
      step: 0,
      maxSteps: 0,
      tools: [],
      interactions: [],
      inputTokens: 0,
      outputTokens: 0,
      toolCalls: 0,
      finishReason: null,
      cost: null
    }
    runs.value = { ...runs.value, [turnId]: run }
    return runs.value[turnId]
  }

  // -----------------------------------------------------------------------
  // Apply actions (idempotent — one per canonical frame)
  // -----------------------------------------------------------------------

  /** `turn.started` → create/replace the run and mark it current. */
  function applyTurnStarted(msg: WsTurnStartedMessage): void {
    pendingTurn.value = false
    const run: AgentRun = {
      turnId: msg.turn_id,
      conversationId: msg.conversation_id,
      status: 'running',
      step: 0,
      maxSteps: 0,
      tools: [],
      interactions: [],
      inputTokens: 0,
      outputTokens: 0,
      toolCalls: 0,
      finishReason: null,
      cost: null
    }
    runs.value = { ...runs.value, [msg.turn_id]: run }
    currentTurnId.value = msg.turn_id
  }

  /** `turn.llm_step` → advance the run's step counter. */
  function applyLlmStep(msg: WsTurnLlmStepMessage): void {
    const run = ensureRun(msg.turn_id)
    run.step = msg.step
  }

  /** `tool.call` → append a `running` tool activity (dedup by executionId). */
  function applyToolCall(msg: WsToolCallMessage): void {
    const run = ensureRun(msg.turn_id)
    if (run.tools.some((t) => t.executionId === msg.execution_id)) return
    const activity: ToolActivity = {
      executionId: msg.execution_id,
      toolName: msg.tool_name,
      args: msg.args,
      status: 'running',
      seq: run.tools.length + run.interactions.length
    }
    run.tools = [...run.tools, activity]
  }

  /**
   * `tool.started` → mark the matching tool activity `running` (idempotent).
   *
   * Create-if-absent: `tool.started` may arrive before its `tool.call`
   * (out of order), so a minimal `running` activity is materialised rather
   * than dropped. A tool already resolved by an out-of-order `tool.result`
   * is left untouched.
   */
  function applyToolStarted(msg: WsToolStartedMessage): void {
    const run = ensureRun(msg.turn_id)
    if (run.tools.some((t) => t.executionId === msg.execution_id)) return
    const activity: ToolActivity = {
      executionId: msg.execution_id,
      toolName: msg.tool_name,
      args: {},
      status: 'running',
      seq: run.tools.length + run.interactions.length
    }
    run.tools = [...run.tools, activity]
  }

  /** `tool.progress` → merge the latest progress snapshot into the activity. */
  function applyToolProgress(msg: WsToolProgressMessage): void {
    const run = ensureRun(msg.turn_id)
    const idx = run.tools.findIndex((t) => t.executionId === msg.execution_id)
    if (idx === -1) return
    const updated: ToolActivity = { ...run.tools[idx], progress: msg.progress }
    run.tools = [...run.tools.slice(0, idx), updated, ...run.tools.slice(idx + 1)]
  }

  /** `tool.result` → resolve the matching tool activity (create if absent). */
  function applyToolResult(msg: WsToolResultMessage): void {
    const run = ensureRun(msg.turn_id)
    // v2: success is derived from the engine `status` vocabulary
    // (ok/error/denied/timeout/…); `status === 'ok'` is the success gate.
    const status: ToolActivity['status'] = msg.status === 'ok' ? 'success' : 'error'
    const idx = run.tools.findIndex((t) => t.executionId === msg.execution_id)
    if (idx === -1) {
      const activity: ToolActivity = {
        executionId: msg.execution_id,
        toolName: msg.tool_name,
        args: {},
        status,
        rawStatus: msg.status,
        result: msg.result,
        contentType: msg.content_type ?? undefined,
        artifactId: msg.artifact_id ?? undefined,
        seq: run.tools.length + run.interactions.length
      }
      run.tools = [...run.tools, activity]
      return
    }
    const updated: ToolActivity = {
      ...run.tools[idx],
      status,
      rawStatus: msg.status,
      result: msg.result,
      contentType: msg.content_type ?? undefined,
      artifactId: msg.artifact_id ?? undefined
    }
    run.tools = [...run.tools.slice(0, idx), updated, ...run.tools.slice(idx + 1)]
  }

  /**
   * `interaction.requested` → append a `pending` interaction activity with
   * its full v2 payload (args/risk/description/reasoning/questions).
   *
   * Idempotent, keyed by `interaction_id`: a repeated request for the same
   * interaction is ignored (the existing entry — possibly already `resolved`
   * — is left untouched).
   */
  function applyInteractionRequested(msg: WsInteractionRequestedMessage): void {
    const run = ensureRun(msg.turn_id)
    if (run.interactions.some((i) => i.interactionId === msg.interaction_id)) return
    const activity: InteractionActivity = {
      interactionId: msg.interaction_id,
      executionId: msg.execution_id,
      kind: msg.kind,
      toolName: msg.tool_name ?? undefined,
      status: 'pending',
      args: msg.args ?? undefined,
      riskLevel: msg.risk_level ?? undefined,
      description: msg.description ?? undefined,
      reasoning: msg.reasoning ?? undefined,
      allowRemember: msg.allow_remember ?? undefined,
      toolMeta: msg.tool_meta ?? undefined,
      questions: msg.questions ?? undefined,
      seq: run.tools.length + run.interactions.length
    }
    run.interactions = [...run.interactions, activity]
  }

  /**
   * `interaction.resolved` → resolve the matching interaction with its
   * outcome (create it already-`resolved` when the request never arrived,
   * mirroring {@link applyToolResult}'s create-if-absent path). Keyed by
   * `interaction_id`.
   */
  function applyInteractionResolved(msg: WsInteractionResolvedMessage): void {
    const run = ensureRun(msg.turn_id)
    const idx = run.interactions.findIndex((i) => i.interactionId === msg.interaction_id)
    if (idx === -1) {
      const activity: InteractionActivity = {
        interactionId: msg.interaction_id,
        executionId: msg.execution_id,
        kind: msg.kind,
        status: 'resolved',
        outcome: msg.outcome,
        seq: run.tools.length + run.interactions.length
      }
      run.interactions = [...run.interactions, activity]
      return
    }
    const updated: InteractionActivity = {
      ...run.interactions[idx],
      status: 'resolved',
      outcome: msg.outcome
    }
    run.interactions = [
      ...run.interactions.slice(0, idx),
      updated,
      ...run.interactions.slice(idx + 1)
    ]
  }

  /** `turn.usage` → record per-step token/tool counters. */
  function applyTurnUsage(msg: WsTurnUsageMessage): void {
    const run = ensureRun(msg.turn_id)
    run.step = msg.step
    run.inputTokens = msg.input_tokens
    run.outputTokens = msg.output_tokens
    run.toolCalls = msg.tool_calls
    run.maxSteps = msg.max_steps
  }

  /** `turn.finished` → mark the run finished with its terminal disposition. */
  function applyTurnFinished(msg: WsTurnFinishedMessage): void {
    const run = ensureRun(msg.turn_id)
    run.status = 'finished'
    run.finishReason = msg.finish_reason ?? null
    run.inputTokens = msg.input_tokens
    run.outputTokens = msg.output_tokens
    run.step = msg.steps
    if (msg.tool_calls != null) run.toolCalls = msg.tool_calls
    run.cost = msg.cost ?? null
  }

  /**
   * Show a fresh "starting" sentinel run during the send → `turn.started` gap.
   *
   * Call this immediately when the user submits a message so the reasoning
   * thread renders a clean zero-state instead of the previous finished run.
   * Automatically cleared by the next {@link applyTurnStarted}.
   */
  function beginPendingTurn(): void {
    pendingTurn.value = true
  }

  /**
   * `turn.error` → drop the pending sentinel.
   *
   * A pre-turn error (assembly/route validation, no `turn_id`) is never
   * followed by `turn.started`/`turn.finished`: without this the sentinel
   * would keep the reasoning thread on "avvio…" forever. For engine errors
   * the sentinel is already cleared and the run closes via `turn.finished`.
   */
  function applyTurnError(): void {
    pendingTurn.value = false
  }

  /** Clear all runs and the current-turn pointer. */
  function reset(): void {
    runs.value = {}
    currentTurnId.value = null
    pendingTurn.value = false
  }

  return {
    // state
    runs,
    currentTurnId,
    pendingTurn,
    // getters
    currentRun,
    runByTurnId,
    pendingConfirmations,
    pendingAskUser,
    // actions
    applyTurnStarted,
    applyLlmStep,
    applyToolCall,
    applyToolStarted,
    applyToolProgress,
    applyToolResult,
    applyInteractionRequested,
    applyInteractionResolved,
    applyTurnUsage,
    applyTurnFinished,
    applyTurnError,
    beginPendingTurn,
    reset
  }
})
