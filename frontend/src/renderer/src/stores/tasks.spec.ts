/**
 * Unit tests for stores/tasks.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store keys task steps by conversation id, folding
 * the `tasks.updated` events-WS frame (full step list) via applyTasksUpdated and
 * fetching the REST snapshot once per conversation via ensureForConversation.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useTasksStore } from './tasks'
import { api } from '../services/api'
import type { TaskStep } from '../types/tasks'

// The store imports `{ api }` from services/api; stub just the getTasks method
// so ensureForConversation/fetch resolve without reaching a backend.
vi.mock('../services/api', () => ({
  api: {
    getTasks: vi.fn(),
  },
}))

const getTasksMock = vi.mocked(api.getTasks)

function step(text: string, status = 'pending'): TaskStep {
  return { step: text, status }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getTasksMock.mockReset()
})

// ---------------------------------------------------------------------------
// applyTasksUpdated (live fold)
// ---------------------------------------------------------------------------

describe('applyTasksUpdated', () => {
  it('folds the pushed steps into tasksFor(id)', () => {
    const s = useTasksStore()
    expect(s.tasksFor('c1')).toEqual([])

    s.applyTasksUpdated({
      conversation_id: 'c1',
      steps: [step('research', 'in_progress'), step('write')],
    })

    expect(s.tasksFor('c1')).toEqual([
      { step: 'research', status: 'in_progress' },
      { step: 'write', status: 'pending' },
    ])
  })

  it('replaces the prior steps on a second update', () => {
    const s = useTasksStore()
    s.applyTasksUpdated({ conversation_id: 'c1', steps: [step('a')] })
    s.applyTasksUpdated({
      conversation_id: 'c1',
      steps: [step('x', 'completed'), step('y', 'in_progress')],
    })

    expect(s.tasksFor('c1')).toEqual([
      { step: 'x', status: 'completed' },
      { step: 'y', status: 'in_progress' },
    ])
  })

  it('keeps conversations independent', () => {
    const s = useTasksStore()
    s.applyTasksUpdated({ conversation_id: 'c1', steps: [step('a')] })
    s.applyTasksUpdated({ conversation_id: 'c2', steps: [step('b', 'completed')] })

    expect(s.tasksFor('c1')).toEqual([{ step: 'a', status: 'pending' }])
    expect(s.tasksFor('c2')).toEqual([{ step: 'b', status: 'completed' }])
  })
})

// ---------------------------------------------------------------------------
// tasksFor
// ---------------------------------------------------------------------------

describe('tasksFor', () => {
  it('returns an empty array for an unknown conversation id', () => {
    const s = useTasksStore()
    expect(s.tasksFor('nope')).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// ensureForConversation (fetch-once)
// ---------------------------------------------------------------------------

describe('ensureForConversation', () => {
  it('calls api.getTasks once and dedupes on the second call', async () => {
    getTasksMock.mockResolvedValue({
      conversation_id: 'c1',
      steps: [step('a', 'completed')],
    })
    const s = useTasksStore()

    await s.ensureForConversation('c1')
    expect(getTasksMock).toHaveBeenCalledTimes(1)
    expect(getTasksMock).toHaveBeenCalledWith('c1')
    expect(s.tasksFor('c1')).toEqual([{ step: 'a', status: 'completed' }])

    await s.ensureForConversation('c1')
    expect(getTasksMock).toHaveBeenCalledTimes(1) // deduped — no second fetch
  })

  it('rolls back the dedup guard on failure so a retry re-fetches', async () => {
    getTasksMock.mockRejectedValueOnce(new Error('boom'))
    const s = useTasksStore()

    await expect(s.ensureForConversation('c1')).rejects.toThrow('boom')
    expect(getTasksMock).toHaveBeenCalledTimes(1)

    getTasksMock.mockResolvedValueOnce({
      conversation_id: 'c1',
      steps: [step('a')],
    })
    await s.ensureForConversation('c1')
    expect(getTasksMock).toHaveBeenCalledTimes(2)
    expect(s.tasksFor('c1')).toEqual([{ step: 'a', status: 'pending' }])
  })
})

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

describe('reset', () => {
  it('clears all cached task lists and the fetched-once guard', async () => {
    getTasksMock.mockResolvedValue({ conversation_id: 'c1', steps: [step('a')] })
    const s = useTasksStore()
    await s.ensureForConversation('c1')
    expect(s.tasksFor('c1')).toHaveLength(1)

    s.reset()
    expect(s.tasksFor('c1')).toEqual([])

    // Guard cleared too: ensureForConversation fetches again after reset.
    await s.ensureForConversation('c1')
    expect(getTasksMock).toHaveBeenCalledTimes(2)
  })
})
