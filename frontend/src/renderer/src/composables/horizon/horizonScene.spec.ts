/**
 * Unit tests for the pure Horizon scene derivation module.
 * Pure functions only — no Vue, no Pinia, runnable in the node env.
 */
import { describe, it, expect } from 'vitest'

import {
  deriveSceneState,
  deriveLineMode,
  deriveSkyMode,
  manuscriptView,
  thinkingSignalNext,
  THINKING_SIGNAL_IDLE,
  lastThinkingLine,
  notchPositions,
  planView,
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
    isThinking: false,
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
      composerActive: false,
      isThinking: false
    })
    expect(state).toBe('quiet')
  })
})

describe('deriveSceneState — thinking', () => {
  it('thinking while streaming with a live reasoning signal and no work', () => {
    expect(deriveSceneState(inputs({ isStreaming: true, isThinking: true }))).toBe('thinking')
  })

  it('working wins over thinking (tools or live plan)', () => {
    expect(
      deriveSceneState(inputs({ isStreaming: true, isThinking: true, activeToolCount: 1 }))
    ).toBe('working')
    expect(
      deriveSceneState(
        inputs({ isStreaming: true, isThinking: true, planSteps: [step('a', 'in_progress')] })
      )
    ).toBe('working')
  })

  it('thinking requires streaming (stale signal after cancel is inert)', () => {
    expect(deriveSceneState(inputs({ isThinking: true }))).toBe('quiet')
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

describe('deriveLineMode — thinking', () => {
  it('thinking keeps the breathing line (life comes from impulses/sky)', () => {
    expect(deriveLineMode('thinking', inputs({ isStreaming: true, isThinking: true }))).toBe(
      'breathe'
    )
  })
})

describe('deriveSkyMode', () => {
  it('wakes the constellation whenever reasoning is live, even inside working', () => {
    expect(deriveSkyMode('thinking', inputs({ isThinking: true }))).toBe('thinking')
    expect(deriveSkyMode('working', inputs({ isThinking: true }))).toBe('thinking')
  })

  it('working without reasoning drives the spores', () => {
    expect(deriveSkyMode('working', inputs())).toBe('working')
  })

  it('everything else is idle', () => {
    expect(deriveSkyMode('quiet', inputs())).toBe('idle')
    expect(deriveSkyMode('responding', inputs())).toBe('idle')
    expect(deriveSkyMode('listening', inputs())).toBe('idle')
  })
})

describe('thinkingSignalNext', () => {
  it('turns on when thinking grows, off when content grows', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    expect(s.active).toBe(true)
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 5, isStreaming: true })
    expect(s.active).toBe(false)
  })

  it('re-activates when the model reasons again mid-turn (tool loop)', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 20, isStreaming: true })
    expect(s.active).toBe(false)
    s = thinkingSignalNext(s, { thinkingLen: 25, contentLen: 20, isStreaming: true })
    expect(s.active).toBe(true)
  })

  it('content growth wins when both grow in the same tick', () => {
    const s = thinkingSignalNext(
      { thinkingLen: 5, contentLen: 5, active: true },
      { thinkingLen: 9, contentLen: 9, isStreaming: true }
    )
    expect(s.active).toBe(false)
  })

  it('stream end and buffer resets deactivate cleanly', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 0, isStreaming: false })
    expect(s.active).toBe(false)
    // nuovo turno: gli accumulatori ripartono da zero, poi il thinking cresce
    s = thinkingSignalNext(s, { thinkingLen: 3, contentLen: 0, isStreaming: true })
    expect(s.active).toBe(true)
  })
})

describe('lastThinkingLine', () => {
  it('returns the last meaningful line, skipping blanks and iteration separators', () => {
    expect(lastThinkingLine('prima\n\nseconda\n---\n\n')).toBe('seconda')
    expect(lastThinkingLine('')).toBe('')
  })

  it('truncates long lines with an ellipsis', () => {
    const long = 'x'.repeat(200)
    const out = lastThinkingLine(long)
    expect(out.length).toBe(120)
    expect(out.endsWith('…')).toBe(true)
  })
})

describe('manuscriptView', () => {
  const plan = (n: number, completed: number): ReturnType<typeof step>[] =>
    Array.from({ length: n }, (_, i) =>
      step(
        `passo ${i + 1}`,
        i < completed ? 'completed' : i === completed ? 'in_progress' : 'pending'
      )
    )

  it('short plans pass through untouched', () => {
    const items = manuscriptView(plan(5, 2))
    expect(items).toHaveLength(5)
    expect(items.every((it) => it.kind === 'step')).toBe(true)
  })

  it('long plans collapse the oldest completed steps, keeping the last 2', () => {
    const items = manuscriptView(plan(10, 6))
    expect(items[0]).toEqual({ kind: 'collapsed', count: 4 })
    const stepRows = items.filter((it) => it.kind === 'step')
    expect(
      stepRows.filter((it) => it.kind === 'step' && it.step.status === 'completed')
    ).toHaveLength(2)
  })

  it('still-too-long plans get a "+N" tail within the cap', () => {
    const items = manuscriptView(plan(15, 2))
    const last = items[items.length - 1]
    expect(last.kind).toBe('more')
    expect(items.length).toBeLessThanOrEqual(8) // maxVisible 7 + eventuale riga collassata
  })

  it('an all-completed plan collapses to the counter + last two', () => {
    const items = manuscriptView(plan(9, 9))
    expect(items[0]).toEqual({ kind: 'collapsed', count: 7 })
    expect(items).toHaveLength(3)
  })

  it('empty plan → empty manuscript', () => {
    expect(manuscriptView([])).toEqual([])
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
