/**
 * Unit tests for stores/backgroundTasks.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store folds `background_task.updated` events-WS
 * frames (full task snapshot) via applyBackgroundTaskUpdated — no REST fetch.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useBackgroundTasksStore, type BackgroundTaskInfo } from './backgroundTasks'

function frame(overrides: Record<string, unknown> = {}): BackgroundTaskInfo {
  return {
    type: 'background_task.updated',
    origin: 'agent',
    task_id: 'bt-1',
    kind: 'subagent',
    label: 'Research',
    status: 'running',
    progress: 0.5,
    detail: 'step 3/6',
    conversation_id: 'c1',
    updated_at: '2026-07-11T12:00:00+00:00',
    ...overrides
  } as BackgroundTaskInfo
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('backgroundTasks store', () => {
  it('folds full snapshots by task id', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.applyBackgroundTaskUpdated(frame({ status: 'completed', progress: 1 }))
    expect(store.all).toHaveLength(1)
    expect(store.byId['bt-1'].status).toBe('completed')
  })

  it('active filters running tasks', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.applyBackgroundTaskUpdated(frame({ task_id: 'bt-2', status: 'failed' }))
    expect(store.active.map((t) => t.task_id)).toEqual(['bt-1'])
  })

  it('reset clears everything', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.reset()
    expect(store.all).toHaveLength(0)
  })
})
