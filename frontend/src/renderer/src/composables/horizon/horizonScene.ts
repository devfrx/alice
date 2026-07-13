/**
 * horizonScene.ts — Pure derivation for the Horizon assistant scene.
 *
 * Maps plain snapshots of the voice/chat/tasks stores to a single scene state
 * and the line's visual mechanic. One state active at a time, with explicit
 * priority: working ▸ responding ▸ listening ▸ quiet. Desk windows are an
 * orthogonal presentation layer — they never affect the ambient scene state.
 *
 * Pure functions only (no Vue imports) so the whole scene brain is unit
 * testable in the node environment.
 */
import type { TaskStep } from '../../types/tasks'

/** The four scene states (spec §3). */
export type HorizonState = 'quiet' | 'listening' | 'responding' | 'working'

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
}

/** Whether the plan exists and is not yet fully completed. */
function planActive(steps: TaskStep[]): boolean {
  return steps.length > 0 && steps.some((s) => s.status !== 'completed')
}

/** Derive the single active scene state (priority ordered). */
export function deriveSceneState(i: HorizonSceneInputs): HorizonState {
  if (i.isStreaming && (planActive(i.planSteps) || i.activeToolCount > 0)) return 'working'
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

/** Roman numeral for stage captions (Fig. I, II, …). Supports 1..3999. */
export function toRoman(n: number): string {
  const table: Array<[number, string]> = [
    [1000, 'M'],
    [900, 'CM'],
    [500, 'D'],
    [400, 'CD'],
    [100, 'C'],
    [90, 'XC'],
    [50, 'L'],
    [40, 'XL'],
    [10, 'X'],
    [9, 'IX'],
    [5, 'V'],
    [4, 'IV'],
    [1, 'I']
  ]
  let out = ''
  for (const [v, s] of table) {
    while (n >= v) {
      out += s
      n -= v
    }
  }
  return out
}
