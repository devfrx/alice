/**
 * useAgentActivity — Derive a unified activity feed for an agent run.
 *
 * The planner often produces a coarse high-level plan (sometimes just
 * a single step) but the LLM internally fires many tool calls to
 * satisfy it.  Without surfacing those real tool calls, the activity
 * UI shows almost nothing useful.
 *
 * This composable interleaves:
 *   (a) the plan steps + critic verdicts coming from the AgentRun
 *       state machine, and
 *   (b) the actual tool calls executed by the assistant, extracted
 *       from the conversation messages between `user_message_id` and
 *       `final_assistant_message_id`.
 *
 * Pure derivation — no side effects.  Reads `currentConversation`
 * directly (NOT the version-filtered `messages` computed) since
 * tool/assistant intermediate frames are rarely versioned.
 */

import { computed, type ComputedRef, type Ref } from 'vue'

import { useChatStore } from '../stores/chat'
import { humanizeTool, summarizeToolArgs, toolCategory } from '../utils/agentLabels'
import type {
  AgentRun,
  StepStatus,
  Verdict,
} from '../types/agent'
import type { ChatMessage, ToolCall } from '../types/chat'

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** A single tool invocation observed inside the run window. */
export interface ToolActivityItem {
  kind: 'tool_call'
  /** OpenAI `tool_call_id` — used to match the result frame. */
  callId: string
  /** Raw backend tool name (e.g. `web_search_web_search`). */
  toolName: string
  /** Humanised present-progressive label (e.g. `Cerco sul web`). */
  toolLabel: string
  /** Single-line summary of the call's arguments. */
  argsSummary: string
  /** Lifecycle status of this individual call. */
  status: 'pending' | 'running' | 'done' | 'failed'
  /** First ~120 chars of the matching tool result, sanitised. */
  resultPreview: string | null
  /** True when the matching result frame represents an error. */
  resultIsError: boolean
  /** ISO timestamp of the assistant message that emitted the call. */
  timestamp: string
}

/** A planned step from the agent's coarse plan. */
export interface PlanStepItem {
  kind: 'plan_step'
  index: number
  description: string
  expectedOutcome: string | null
  status: StepStatus
  verdict: Verdict | null
  toolHint: string | null
  toolHintLabel: string | null
}

/** Aggregated counters surfaced in the activity header. */
export interface ActivityStats {
  toolCallsTotal: number
  toolCallsByCategory: Record<string, number>
  /** Wall-clock duration in ms (null while still running or unknown). */
  durationMs: number | null
}

/** The unified, ordered activity feed for an agent run. */
export interface ActivityFeed {
  isLive: boolean
  planSteps: PlanStepItem[]
  toolActivity: ToolActivityItem[]
  stats: ActivityStats
  hasAnyActivity: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compact a multiline string into a single line and trim whitespace. */
function _flatten(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** Truncate a string to ~120 chars adding an ellipsis. */
function _previewify(text: string): string {
  const flat = _flatten(text)
  return flat.length > 120 ? `${flat.slice(0, 119)}…` : flat
}

/**
 * Detect whether a tool result represents an error.  We treat the
 * payload as an error if it parses as JSON with a top-level `error`
 * or `isError: true`, or if the raw text starts with the literal
 * `{"error"`.
 */
function _isErrorResult(content: string): boolean {
  const trimmed = content.trimStart()
  if (trimmed.startsWith('{"error"')) return true
  if (/"isError"\s*:\s*true/.test(content)) return true
  try {
    const parsed: unknown = JSON.parse(content)
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as Record<string, unknown>
      if (typeof obj.error === 'string' && obj.error.length > 0) return true
      if (obj.isError === true) return true
    }
  } catch {
    /* not JSON */
  }
  return false
}

/** Safely parse an OpenAI-shaped `tool_call.function.arguments` string. */
function _parseArgs(rawArgs: string): Record<string, unknown> | null {
  if (!rawArgs) return null
  try {
    const parsed: unknown = JSON.parse(rawArgs)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    /* malformed */
  }
  return null
}

/** Mirror of the per-step status logic used by PlanCard / Sidebar. */
function _stepStatus(run: AgentRun, index: number): StepStatus {
  const verdict = run.verdicts[index]
  const current = run.current_step
  const state = run.state

  if (verdict) {
    switch (verdict.action) {
      case 'ok':
        return 'done'
      case 'retry':
        return index === current ? 'in_progress' : 'retry'
      case 'replan':
        return 'done'
      case 'ask_user':
        return 'in_progress'
      case 'abort':
        return 'failed'
    }
  }
  if (state === 'cancelled' || state === 'failed') {
    if (index < current) return 'done'
    if (index === current) return 'failed'
    return 'skipped'
  }
  if (index < current) return 'done'
  if (index === current && (state === 'running' || state === 'planning')) {
    return 'in_progress'
  }
  return 'pending'
}

// ---------------------------------------------------------------------------
// Core derivation
// ---------------------------------------------------------------------------

/**
 * Slice a flat message list down to the window owned by `run`.
 * Returns the messages that lie strictly after `user_message_id` and
 * up to and including `final_assistant_message_id` (or the tail of
 * the conversation when the run is still live).
 */
function _runWindow(run: AgentRun, messages: ChatMessage[]): ChatMessage[] {
  const startIdx = messages.findIndex((m) => m.id === run.user_message_id)
  if (startIdx < 0) return []
  let endIdx = messages.length - 1
  if (run.final_assistant_message_id) {
    const found = messages.findIndex((m) => m.id === run.final_assistant_message_id)
    if (found >= 0) endIdx = found
  }
  if (endIdx < startIdx + 1) return []
  return messages.slice(startIdx + 1, endIdx + 1)
}

/** Build the ordered tool-activity timeline from the run window. */
function _buildToolActivity(window: ChatMessage[]): ToolActivityItem[] {
  // Map call_id → index in `out` for fast result attachment.
  const out: ToolActivityItem[] = []
  const byId = new Map<string, number>()

  for (const msg of window) {
    if (msg.role === 'assistant' && msg.tool_calls?.length) {
      for (const call of msg.tool_calls as ToolCall[]) {
        const args = _parseArgs(call.function.arguments) ?? {}
        const item: ToolActivityItem = {
          kind: 'tool_call',
          callId: call.id,
          toolName: call.function.name,
          toolLabel: humanizeTool(call.function.name),
          argsSummary: summarizeToolArgs(call.function.name, args),
          status: 'running',
          resultPreview: null,
          resultIsError: false,
          timestamp: msg.created_at,
        }
        byId.set(call.id, out.length)
        out.push(item)
      }
      continue
    }
    if (msg.role === 'tool' && msg.tool_call_id) {
      const idx = byId.get(msg.tool_call_id)
      if (idx === undefined) continue
      const item = out[idx]
      const isErr = _isErrorResult(msg.content)
      item.status = isErr ? 'failed' : 'done'
      item.resultIsError = isErr
      item.resultPreview = _previewify(msg.content)
    }
  }

  return out
}

/** Build the high-level plan-step list from the run's plan. */
function _buildPlanSteps(run: AgentRun): PlanStepItem[] {
  if (!run.plan) return []
  return run.plan.steps.map((step, idx) => ({
    kind: 'plan_step' as const,
    index: idx,
    description: step.description,
    expectedOutcome: step.expected_outcome || null,
    status: _stepStatus(run, idx),
    verdict: run.verdicts[idx] ?? null,
    toolHint: step.tool_hint ?? null,
    toolHintLabel: step.tool_hint ? humanizeTool(step.tool_hint) : null,
  }))
}

/** Aggregate tool activity into header counters. */
function _buildStats(
  run: AgentRun,
  toolActivity: ToolActivityItem[],
): ActivityStats {
  const byCategory: Record<string, number> = {}
  for (const t of toolActivity) {
    const cat = toolCategory(t.toolName)
    byCategory[cat] = (byCategory[cat] ?? 0) + 1
  }
  let durationMs: number | null = null
  if (run.started_at) {
    const start = Date.parse(run.started_at)
    const endIso = run.finished_at
    if (Number.isFinite(start)) {
      const end = endIso ? Date.parse(endIso) : Date.now()
      if (Number.isFinite(end) && end >= start) durationMs = end - start
    }
  }
  return {
    toolCallsTotal: toolActivity.length,
    toolCallsByCategory: byCategory,
    durationMs,
  }
}

// ---------------------------------------------------------------------------
// Composable entry
// ---------------------------------------------------------------------------

/**
 * Derive a reactive `ActivityFeed` for the given agent run.  Returns
 * `null` when no run is provided or no conversation is currently
 * loaded.
 */
export function useAgentActivity(
  run: Ref<AgentRun | null>,
): ComputedRef<ActivityFeed | null> {
  const chatStore = useChatStore()

  return computed<ActivityFeed | null>(() => {
    const r = run.value
    if (!r) return null
    const conv = chatStore.currentConversation
    if (!conv) return null
    const messages = conv.messages ?? []
    const window = _runWindow(r, messages)
    const toolActivity = _buildToolActivity(window)
    const planSteps = _buildPlanSteps(r)
    const stats = _buildStats(r, toolActivity)
    const isLive =
      r.state === 'planning' ||
      r.state === 'running' ||
      r.state === 'asked_user'
    const hasAnyActivity = toolActivity.length > 0 || planSteps.length > 0
    return { isLive, planSteps, toolActivity, stats, hasAnyActivity }
  })
}
