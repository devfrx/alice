/**
 * horizonScene.ts — Pure derivation for the Horizon assistant scene.
 *
 * Maps plain snapshots of the voice/chat/tasks stores to a single scene state
 * and the line's visual mechanic. One state active at a time, with explicit
 * priority: working ▸ thinking ▸ responding ▸ listening ▸ quiet. Desk windows
 * are an orthogonal presentation layer — they never affect the ambient scene
 * state.
 *
 * Pure functions only (no Vue imports) so the whole scene brain is unit
 * testable in the node environment.
 */
import type { TaskStep } from '../../types/tasks'

/** The five scene states (spec Horizon Vivo §3.1). */
export type HorizonState = 'quiet' | 'listening' | 'thinking' | 'responding' | 'working'

/** The living backdrop's mode (HorizonSky). */
export type HorizonSkyMode = 'idle' | 'thinking' | 'working'

/** The line's visual mechanic (HorizonLine modes). */
export type HorizonLineMode = 'breathe' | 'tense' | 'pulse' | 'timeline' | 'flow'

/** Plain-value snapshot of everything the scene depends on. */
export interface HorizonSceneInputs {
  isListening: boolean
  isSttProcessing: boolean
  isSpeaking: boolean
  isStreaming: boolean
  activeToolCount: number
  planSteps: TaskStep[]
  composerActive: boolean
  /** Live reasoning signal (useThinkingSignal): thinking tokens are flowing. */
  isThinking: boolean
}

/** Whether the plan exists and is not yet fully completed. */
function planActive(steps: TaskStep[]): boolean {
  return steps.length > 0 && steps.some((s) => s.status !== 'completed')
}

/** Derive the single active scene state (priority ordered). */
export function deriveSceneState(i: HorizonSceneInputs): HorizonState {
  if (i.isStreaming && (planActive(i.planSteps) || i.activeToolCount > 0)) return 'working'
  if (i.isStreaming && i.isThinking) return 'thinking'
  if (i.isStreaming || i.isSpeaking) return 'responding'
  if (i.isListening || i.isSttProcessing || i.composerActive) return 'listening'
  return 'quiet'
}

/** Derive the line mechanic for a scene state. */
export function deriveLineMode(state: HorizonState, i: HorizonSceneInputs): HorizonLineMode {
  switch (state) {
    case 'listening':
      return 'tense'
    case 'responding':
      return i.isSpeaking ? 'pulse' : 'breathe'
    case 'working':
      return i.planSteps.length > 0 ? 'timeline' : 'flow'
    case 'thinking':
      return 'breathe'
    default:
      return 'breathe'
  }
}

/**
 * Notch x-positions for the timeline mode as fractions (0..1) of the line
 * span, centered over the middle 70% so end fades stay clean. Shared by the
 * canvas (ticks/spark) and the DOM labels so they always agree.
 */
export function notchPositions(count: number): number[] {
  if (count <= 0) return []
  if (count === 1) return [0.5]
  return Array.from({ length: count }, (_, i) => 0.15 + (i * 0.7) / (count - 1))
}

/** Plan summary for the working state. */
export interface HorizonPlanView {
  total: number
  completed: number
  /** Index of the step the spark points at; `-1` for an empty plan. */
  activeIndex: number
  statusSentence: string
}

/** Summarise plan steps: active = first in_progress, else first pending, else last. */
export function planView(steps: TaskStep[]): HorizonPlanView {
  const total = steps.length
  const completed = steps.filter((s) => s.status === 'completed').length
  let activeIndex = steps.findIndex((s) => s.status === 'in_progress')
  if (activeIndex < 0) activeIndex = steps.findIndex((s) => s.status === 'pending')
  if (activeIndex < 0) activeIndex = total - 1
  return { total, completed, activeIndex, statusSentence: steps[activeIndex]?.step ?? '' }
}

/** Sky mode: the constellation wakes on live reasoning, spores on work. */
export function deriveSkyMode(state: HorizonState, i: HorizonSceneInputs): HorizonSkyMode {
  if (i.isThinking && (state === 'thinking' || state === 'working')) return 'thinking'
  if (state === 'working') return 'working'
  return 'idle'
}

/* ── thinking signal (edge-triggered, non level-based: works in tool loops) ── */

export interface ThinkingSignalSnapshot {
  thinkingLen: number
  contentLen: number
  isStreaming: boolean
}

export interface ThinkingSignalState {
  thinkingLen: number
  contentLen: number
  active: boolean
}

export const THINKING_SIGNAL_IDLE: Readonly<ThinkingSignalState> = Object.freeze({
  thinkingLen: 0,
  contentLen: 0,
  active: false
})

/**
 * Pure reducer for the "is Alice reasoning right now" signal: thinking growth
 * activates it, visible-content growth deactivates it (content wins when both
 * grow in one tick), stream end and buffer resets deactivate/re-baseline.
 */
export function thinkingSignalNext(
  prev: ThinkingSignalState,
  snap: ThinkingSignalSnapshot
): ThinkingSignalState {
  if (!snap.isStreaming) {
    return { thinkingLen: snap.thinkingLen, contentLen: snap.contentLen, active: false }
  }
  let active = prev.active
  if (snap.thinkingLen < prev.thinkingLen || snap.contentLen < prev.contentLen) {
    // Buffers were reset (new turn): re-baseline on what is present now.
    active = snap.thinkingLen > 0 && snap.contentLen === 0
  } else if (snap.contentLen > prev.contentLen) {
    active = false
  } else if (snap.thinkingLen > prev.thinkingLen) {
    active = true
  }
  return { thinkingLen: snap.thinkingLen, contentLen: snap.contentLen, active }
}

/** Last meaningful line of the thinking stream (marginalia text). */
export function lastThinkingLine(content: string, maxChars = 120): string {
  const lines = content.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim()
    if (line === '' || line === '---') continue
    return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line
  }
  return ''
}

/* ── manuscript plan (Horizon Vivo §5) ── */

export type HorizonManuscriptItem =
  | { kind: 'step'; index: number; step: TaskStep }
  | { kind: 'collapsed'; count: number }
  | { kind: 'more'; count: number }

/**
 * Rows for the manuscript plan. Long plans collapse their oldest completed
 * steps into a counter row (always keeping the last 2 completed) and, if
 * still over budget, tail-collapse the far future into a "+N" row.
 */
export function manuscriptView(steps: TaskStep[], maxVisible = 7): HorizonManuscriptItem[] {
  const all: HorizonManuscriptItem[] = steps.map((step, index) => ({ kind: 'step', index, step }))
  if (all.length <= maxVisible) return all

  const completedIdx = steps
    .map((s, index) => ({ s, index }))
    .filter(({ s }) => s.status === 'completed')
    .map(({ index }) => index)
  const keepCompleted = new Set(completedIdx.slice(-2))
  const collapsedCount = completedIdx.length - keepCompleted.size

  let items = all.filter(
    (it) => it.kind !== 'step' || it.step.status !== 'completed' || keepCompleted.has(it.index)
  )
  if (collapsedCount > 0) items = [{ kind: 'collapsed', count: collapsedCount }, ...items]

  const budget = maxVisible + (collapsedCount > 0 ? 1 : 0)
  if (items.length > budget) {
    const hiddenSteps = items.slice(budget - 1).filter((it) => it.kind === 'step').length
    items = [...items.slice(0, budget - 1), { kind: 'more', count: hiddenSteps }]
  }
  return items
}
