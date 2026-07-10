/**
 * Unit tests for stores/agentRun.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store folds the canonical turn-event stream (see
 * types/turn.ts, mirroring backend/services/turn/events.py) into per-turn
 * AgentRun view-models keyed by `turnId`.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAgentRunStore } from './agentRun'
import type {
  WsInteractionRequestedMessage,
  WsInteractionResolvedMessage,
  WsToolCallMessage,
  WsToolResultMessage,
  WsTurnFinishedMessage,
  WsTurnLlmStepMessage,
  WsTurnStartedMessage,
  WsTurnUsageMessage
} from '../types/turn'

// ---------------------------------------------------------------------------
// Frame factories
// ---------------------------------------------------------------------------

function started(turnId: string, conversationId = 'conv-1'): WsTurnStartedMessage {
  return { type: 'turn.started', turn_id: turnId, conversation_id: conversationId }
}

function llmStep(turnId: string, step: number): WsTurnLlmStepMessage {
  return { type: 'turn.llm_step', turn_id: turnId, step }
}

function toolCall(
  turnId: string,
  executionId: string,
  toolName = 'web_search',
  args: Record<string, unknown> = { q: 'alice' }
): WsToolCallMessage {
  return {
    type: 'tool.call',
    turn_id: turnId,
    execution_id: executionId,
    tool_name: toolName,
    args
  }
}

function toolResult(
  turnId: string,
  executionId: string,
  overrides: Partial<WsToolResultMessage> = {}
): WsToolResultMessage {
  return {
    type: 'tool.result',
    turn_id: turnId,
    execution_id: executionId,
    tool_name: 'web_search',
    success: true,
    result: 'ok',
    ...overrides
  }
}

function interactionRequested(
  turnId: string,
  executionId: string,
  overrides: Partial<WsInteractionRequestedMessage> = {}
): WsInteractionRequestedMessage {
  return {
    type: 'interaction.requested',
    turn_id: turnId,
    execution_id: executionId,
    kind: 'tool_confirmation',
    tool_name: 'run_terminal_command',
    ...overrides
  }
}

function interactionResolved(
  turnId: string,
  executionId: string,
  overrides: Partial<WsInteractionResolvedMessage> = {}
): WsInteractionResolvedMessage {
  return {
    type: 'interaction.resolved',
    turn_id: turnId,
    execution_id: executionId,
    kind: 'tool_confirmation',
    outcome: 'approved',
    ...overrides
  }
}

function usage(turnId: string, overrides: Partial<WsTurnUsageMessage> = {}): WsTurnUsageMessage {
  return {
    type: 'turn.usage',
    turn_id: turnId,
    step: 1,
    input_tokens: 100,
    output_tokens: 20,
    tool_calls: 1,
    max_steps: 8,
    ...overrides
  }
}

function finished(
  turnId: string,
  overrides: Partial<WsTurnFinishedMessage> = {}
): WsTurnFinishedMessage {
  return {
    type: 'turn.finished',
    turn_id: turnId,
    finish_reason: 'stop',
    input_tokens: 100,
    output_tokens: 20,
    steps: 1,
    ...overrides
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

describe('happy-path turn', () => {
  it('folds a full started→llm_step→tool.call→tool.result→usage→finished sequence', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyLlmStep(llmStep('t1', 1))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyToolResult(toolResult('t1', 'e1'))
    s.applyTurnUsage(usage('t1'))
    s.applyTurnFinished(finished('t1'))

    const run = s.currentRun
    expect(run).not.toBeNull()
    expect(run!.turnId).toBe('t1')
    expect(run!.conversationId).toBe('conv-1')
    expect(run!.status).toBe('finished')
    expect(run!.finishReason).toBe('stop')
    expect(run!.step).toBe(1)
    expect(run!.maxSteps).toBe(8)
    expect(run!.inputTokens).toBe(100)
    expect(run!.outputTokens).toBe(20)
    expect(run!.toolCalls).toBe(1)
    expect(run!.tools).toHaveLength(1)
    expect(run!.tools[0]).toMatchObject({
      executionId: 'e1',
      toolName: 'web_search',
      status: 'success',
      result: 'ok'
    })
    expect(run!.tools[0].args).toEqual({ q: 'alice' })
  })

  it('dedups a repeated tool.call by executionId', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyToolCall(toolCall('t1', 'e1', 'other_tool'))
    expect(s.currentRun!.tools).toHaveLength(1)
    // The original running activity is left untouched.
    expect(s.currentRun!.tools[0].status).toBe('running')
    expect(s.currentRun!.tools[0].toolName).toBe('web_search')
  })
})

// ---------------------------------------------------------------------------
// tool.result handling
// ---------------------------------------------------------------------------

describe('tool.result handling', () => {
  it('maps success:false to status error', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyToolResult(toolResult('t1', 'e1', { success: false, result: 'boom' }))
    expect(s.currentRun!.tools[0].status).toBe('error')
    expect(s.currentRun!.tools[0].result).toBe('boom')
  })

  it('propagates content_type / artifact_id to contentType / artifactId', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyToolResult(toolResult('t1', 'e1', { content_type: 'image/png', artifact_id: 'art-9' }))
    const tool = s.currentRun!.tools[0]
    expect(tool.contentType).toBe('image/png')
    expect(tool.artifactId).toBe('art-9')
  })

  it('creates the activity when tool.result arrives before tool.call (out of order)', () => {
    const s = useAgentRunStore()
    // No turn.started, no tool.call — the result frame arrives first.
    s.applyToolResult(toolResult('t1', 'e1', { success: true, result: 'early' }))

    const run = s.runByTurnId('t1')
    expect(run).not.toBeNull()
    expect(run!.status).toBe('running')
    expect(run!.tools).toHaveLength(1)
    expect(run!.tools[0]).toMatchObject({
      executionId: 'e1',
      status: 'success',
      result: 'early'
    })

    // A subsequent tool.call for the same executionId must NOT duplicate it.
    s.applyToolCall(toolCall('t1', 'e1'))
    expect(s.runByTurnId('t1')!.tools).toHaveLength(1)
  })
})

// ---------------------------------------------------------------------------
// interaction handling
// ---------------------------------------------------------------------------

describe('interaction handling', () => {
  it('initialises interactions to [] on turn.started', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    expect(s.currentRun!.interactions).toEqual([])
  })

  it('appends a pending entry on interaction.requested', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1'))
    expect(s.currentRun!.interactions).toHaveLength(1)
    expect(s.currentRun!.interactions[0]).toMatchObject({
      executionId: 'x1',
      kind: 'tool_confirmation',
      toolName: 'run_terminal_command',
      status: 'pending'
    })
  })

  it('dedups a repeated interaction.requested by executionId', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1', { kind: 'ask_user' }))
    expect(s.currentRun!.interactions).toHaveLength(1)
    // The original pending entry is left untouched.
    expect(s.currentRun!.interactions[0].kind).toBe('tool_confirmation')
    expect(s.currentRun!.interactions[0].status).toBe('pending')
  })

  it('flips a pending entry to resolved with its outcome', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1'))
    s.applyInteractionResolved(interactionResolved('t1', 'x1', { outcome: 'rejected' }))
    const io = s.currentRun!.interactions[0]
    expect(io.status).toBe('resolved')
    expect(io.outcome).toBe('rejected')
    // The requested-side metadata (tool name) is preserved across the flip.
    expect(io.toolName).toBe('run_terminal_command')
  })

  it('creates a resolved entry when resolved arrives before requested (out of order)', () => {
    const s = useAgentRunStore()
    // No turn.started, no requested — the resolved frame arrives first.
    s.applyInteractionResolved(
      interactionResolved('t1', 'x1', { kind: 'ask_user', outcome: 'answered' })
    )

    const run = s.runByTurnId('t1')
    expect(run).not.toBeNull()
    expect(run!.status).toBe('running')
    expect(run!.interactions).toHaveLength(1)
    expect(run!.interactions[0]).toMatchObject({
      executionId: 'x1',
      kind: 'ask_user',
      status: 'resolved',
      outcome: 'answered'
    })

    // A subsequent requested for the same executionId must NOT duplicate it.
    s.applyInteractionRequested(interactionRequested('t1', 'x1', { kind: 'ask_user' }))
    expect(s.runByTurnId('t1')!.interactions).toHaveLength(1)
  })

  it('keeps an entry pending forever when no resolved arrives (client disconnect)', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1', { kind: 'ask_user' }))
    // The socket is gone — no interaction.resolved will ever arrive.
    const io = s.currentRun!.interactions[0]
    expect(io.status).toBe('pending')
    expect(io.outcome).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

describe('reset', () => {
  it('clears all runs and the current pointer', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyInteractionRequested(interactionRequested('t1', 'x1'))
    expect(s.currentRun).not.toBeNull()
    expect(s.currentRun!.interactions).toHaveLength(1)

    s.reset()
    expect(s.currentTurnId).toBeNull()
    expect(s.currentRun).toBeNull()
    expect(s.runByTurnId('t1')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Multiple turns
// ---------------------------------------------------------------------------

describe('multiple turns', () => {
  it('tracks runs independently with currentTurnId following the latest turn.started', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1', 'conv-a'))
    s.applyToolCall(toolCall('t1', 'e1'))
    s.applyTurnStarted(started('t2', 'conv-b'))
    s.applyToolCall(toolCall('t2', 'e2'))

    expect(s.currentTurnId).toBe('t2')
    expect(s.currentRun!.turnId).toBe('t2')
    expect(s.currentRun!.conversationId).toBe('conv-b')

    // t1 remains intact and independent of t2.
    const t1 = s.runByTurnId('t1')
    expect(t1).not.toBeNull()
    expect(t1!.conversationId).toBe('conv-a')
    expect(t1!.tools).toHaveLength(1)
    expect(t1!.tools[0].executionId).toBe('e1')
    expect(s.runByTurnId('t2')!.tools[0].executionId).toBe('e2')
  })
})

// ---------------------------------------------------------------------------
// seq — monotonic insertion order across tools + interactions
// ---------------------------------------------------------------------------

describe('seq', () => {
  it('assigns monotonic seq across interleaved tools and interactions', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyToolCall({
      type: 'tool.call',
      turn_id: 't1',
      execution_id: 'e1',
      tool_name: 'web_search',
      args: {}
    })
    s.applyInteractionRequested({
      type: 'interaction.requested',
      turn_id: 't1',
      execution_id: 'e2',
      kind: 'tool_confirmation',
      tool_name: 'write_file'
    })
    s.applyToolCall({
      type: 'tool.call',
      turn_id: 't1',
      execution_id: 'e3',
      tool_name: 'read_file',
      args: {}
    })
    const run = s.runByTurnId('t1')!
    expect(run.tools.find((t) => t.executionId === 'e1')!.seq).toBe(0)
    expect(run.interactions.find((i) => i.executionId === 'e2')!.seq).toBe(1)
    expect(run.tools.find((t) => t.executionId === 'e3')!.seq).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// beginPendingTurn — optimistic "sending" state
// ---------------------------------------------------------------------------

describe('beginPendingTurn', () => {
  it('beginPendingTurn shows a fresh pending run, not the prior finished one', () => {
    const s = useAgentRunStore()
    s.applyTurnStarted(started('t1'))
    s.applyTurnFinished({
      type: 'turn.finished',
      turn_id: 't1',
      finish_reason: 'stop',
      input_tokens: 10,
      output_tokens: 5,
      steps: 1
    })
    expect(s.currentRun!.status).toBe('finished')
    s.beginPendingTurn()
    expect(s.currentRun!.status).toBe('running')
    expect(s.currentRun!.step).toBe(0)
    expect(s.currentRun!.tools).toEqual([])
    expect(s.currentRun!.finishReason).toBeNull()
  })

  it('applyTurnStarted clears the pending flag', () => {
    const s = useAgentRunStore()
    s.beginPendingTurn()
    expect(s.currentRun!.status).toBe('running')
    s.applyTurnStarted(started('t2'))
    expect(s.currentTurnId).toBe('t2')
    expect(s.currentRun!.turnId).toBe('t2')
  })
})
