/**
 * Unit tests for the pure Horizon scene derivation module.
 * Pure functions only — no Vue, no Pinia, runnable in the node env.
 */
import { describe, it, expect } from 'vitest'

import {
  deriveSceneState,
  deriveLineMode,
  notchPositions,
  planView,
  toRoman,
  type HorizonSceneInputs
} from './horizonScene'
import type { TaskStep } from '../../types/tasks'

function inputs(over: Partial<HorizonSceneInputs> = {}): HorizonSceneInputs {
  return {
    isListening: false,
    isSttProcessing: false,
    isSpeaking: false,
    isStreaming: false,
    activeToolCount: 0,
    planSteps: [],
    composerActive: false,
    ...over
  }
}

const step = (s: string, status = 'pending'): TaskStep => ({ step: s, status })

describe('deriveSceneState', () => {
  it('is quiet when nothing is happening', () => {
    expect(deriveSceneState(inputs())).toBe('quiet')
  })

  it('listening on mic / STT / composer', () => {
    expect(deriveSceneState(inputs({ isListening: true }))).toBe('listening')
    expect(deriveSceneState(inputs({ isSttProcessing: true }))).toBe('listening')
    expect(deriveSceneState(inputs({ composerActive: true }))).toBe('listening')
  })

  it('responding while streaming plain text or speaking', () => {
    expect(deriveSceneState(inputs({ isStreaming: true }))).toBe('responding')
    expect(deriveSceneState(inputs({ isSpeaking: true }))).toBe('responding')
  })

  it('working while streaming with active tools or an unfinished plan', () => {
    expect(deriveSceneState(inputs({ isStreaming: true, activeToolCount: 1 }))).toBe('working')
    expect(
      deriveSceneState(inputs({ isStreaming: true, planSteps: [step('a', 'in_progress')] }))
    ).toBe('working')
  })

  it('a fully completed plan no longer forces working', () => {
    expect(
      deriveSceneState(inputs({ isStreaming: true, planSteps: [step('a', 'completed')] }))
    ).toBe('responding')
  })

  it('responding wins over listening (hot mic while the model streams)', () => {
    expect(deriveSceneState(inputs({ isStreaming: true, isListening: true }))).toBe('responding')
  })

  it('never returns presenting: windows are orthogonal to the scene', () => {
    const state = deriveSceneState({
      isListening: false,
      isSttProcessing: false,
      isSpeaking: false,
      isStreaming: false,
      activeToolCount: 0,
      planSteps: [],
      composerActive: false
    })
    expect(state).toBe('quiet')
  })
})

describe('deriveLineMode', () => {
  it('maps states to line mechanics', () => {
    expect(deriveLineMode('quiet', inputs())).toBe('breathe')
    expect(deriveLineMode('listening', inputs({ isListening: true }))).toBe('tense')
    expect(deriveLineMode('responding', inputs({ isSpeaking: true }))).toBe('pulse')
    expect(deriveLineMode('responding', inputs({ isStreaming: true }))).toBe('breathe')
    expect(deriveLineMode('working', inputs({ planSteps: [step('a')] }))).toBe('timeline')
    expect(deriveLineMode('working', inputs({ activeToolCount: 1 }))).toBe('flow')
  })
})

describe('notchPositions', () => {
  it('returns centered fractions across the span', () => {
    expect(notchPositions(0)).toEqual([])
    expect(notchPositions(1)).toEqual([0.5])
    expect(notchPositions(3)).toEqual([0.15, 0.5, 0.85])
  })
})

describe('planView', () => {
  it('summarises a plan: active = first in_progress, else first pending', () => {
    const v = planView([step('uno', 'completed'), step('due', 'in_progress'), step('tre')])
    expect(v).toEqual({ total: 3, completed: 1, activeIndex: 1, statusSentence: 'due' })
  })
  it('falls back to the first pending, then the last step', () => {
    expect(planView([step('uno', 'completed'), step('due')]).activeIndex).toBe(1)
    expect(planView([step('uno', 'completed')]).activeIndex).toBe(0)
    expect(planView([]).statusSentence).toBe('')
  })
})

describe('toRoman', () => {
  it('formats stage captions', () => {
    expect(toRoman(1)).toBe('I')
    expect(toRoman(4)).toBe('IV')
    expect(toRoman(9)).toBe('IX')
    expect(toRoman(14)).toBe('XIV')
  })

  it('degrades to an empty string below 1', () => {
    expect(toRoman(0)).toBe('')
  })
})
