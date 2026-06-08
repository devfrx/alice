/**
 * Unit tests for stores/plan.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store keys plan steps by conversation id, folding
 * the `plan.updated` events-WS frame (full step list) via applyPlanUpdated and
 * fetching the REST snapshot once per conversation via ensureForConversation.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { usePlanStore } from './plan'
import { api } from '../services/api'
import type { PlanStep } from '../types/plan'

// The store imports `{ api }` from services/api; stub just the getPlan method
// so ensureForConversation/fetch resolve without reaching a backend.
vi.mock('../services/api', () => ({
  api: {
    getPlan: vi.fn(),
  },
}))

const getPlanMock = vi.mocked(api.getPlan)

function step(text: string, status = 'pending'): PlanStep {
  return { step: text, status }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getPlanMock.mockReset()
})

// ---------------------------------------------------------------------------
// applyPlanUpdated (live fold)
// ---------------------------------------------------------------------------

describe('applyPlanUpdated', () => {
  it('folds the pushed steps into planFor(id)', () => {
    const s = usePlanStore()
    expect(s.planFor('c1')).toEqual([])

    s.applyPlanUpdated({
      conversation_id: 'c1',
      steps: [step('research', 'in_progress'), step('write')],
    })

    expect(s.planFor('c1')).toEqual([
      { step: 'research', status: 'in_progress' },
      { step: 'write', status: 'pending' },
    ])
  })

  it('replaces the prior steps on a second update', () => {
    const s = usePlanStore()
    s.applyPlanUpdated({ conversation_id: 'c1', steps: [step('a')] })
    s.applyPlanUpdated({
      conversation_id: 'c1',
      steps: [step('x', 'completed'), step('y', 'in_progress')],
    })

    expect(s.planFor('c1')).toEqual([
      { step: 'x', status: 'completed' },
      { step: 'y', status: 'in_progress' },
    ])
  })

  it('keeps conversations independent', () => {
    const s = usePlanStore()
    s.applyPlanUpdated({ conversation_id: 'c1', steps: [step('a')] })
    s.applyPlanUpdated({ conversation_id: 'c2', steps: [step('b', 'completed')] })

    expect(s.planFor('c1')).toEqual([{ step: 'a', status: 'pending' }])
    expect(s.planFor('c2')).toEqual([{ step: 'b', status: 'completed' }])
  })
})

// ---------------------------------------------------------------------------
// planFor
// ---------------------------------------------------------------------------

describe('planFor', () => {
  it('returns an empty array for an unknown conversation id', () => {
    const s = usePlanStore()
    expect(s.planFor('nope')).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// ensureForConversation (fetch-once)
// ---------------------------------------------------------------------------

describe('ensureForConversation', () => {
  it('calls api.getPlan once and dedupes on the second call', async () => {
    getPlanMock.mockResolvedValue({
      conversation_id: 'c1',
      steps: [step('a', 'completed')],
    })
    const s = usePlanStore()

    await s.ensureForConversation('c1')
    expect(getPlanMock).toHaveBeenCalledTimes(1)
    expect(getPlanMock).toHaveBeenCalledWith('c1')
    expect(s.planFor('c1')).toEqual([{ step: 'a', status: 'completed' }])

    await s.ensureForConversation('c1')
    expect(getPlanMock).toHaveBeenCalledTimes(1) // deduped — no second fetch
  })

  it('rolls back the dedup guard on failure so a retry re-fetches', async () => {
    getPlanMock.mockRejectedValueOnce(new Error('boom'))
    const s = usePlanStore()

    await expect(s.ensureForConversation('c1')).rejects.toThrow('boom')
    expect(getPlanMock).toHaveBeenCalledTimes(1)

    getPlanMock.mockResolvedValueOnce({
      conversation_id: 'c1',
      steps: [step('a')],
    })
    await s.ensureForConversation('c1')
    expect(getPlanMock).toHaveBeenCalledTimes(2)
    expect(s.planFor('c1')).toEqual([{ step: 'a', status: 'pending' }])
  })
})

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

describe('reset', () => {
  it('clears all cached plans and the fetched-once guard', async () => {
    getPlanMock.mockResolvedValue({ conversation_id: 'c1', steps: [step('a')] })
    const s = usePlanStore()
    await s.ensureForConversation('c1')
    expect(s.planFor('c1')).toHaveLength(1)

    s.reset()
    expect(s.planFor('c1')).toEqual([])

    // Guard cleared too: ensureForConversation fetches again after reset.
    await s.ensureForConversation('c1')
    expect(getPlanMock).toHaveBeenCalledTimes(2)
  })
})
