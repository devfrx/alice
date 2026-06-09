/**
 * Unit tests for utils/turnActivity.ts
 *
 * Pure-function tests (vitest node env, no component mount). `summarizeTools`
 * buckets a turn's tool-activity list (see types/turn.ts) by lifecycle status.
 */
import { describe, it, expect } from 'vitest'

import { summarizeTools } from './turnActivity'
import type { ToolActivity } from '../types/turn'

/** Build a minimal ToolActivity carrying the given status. */
function activity(executionId: string, status: ToolActivity['status']): ToolActivity {
  return { executionId, toolName: 'web_search', args: {}, status, seq: 0 }
}

describe('summarizeTools', () => {
  it('returns all zeros for an empty list', () => {
    expect(summarizeTools([])).toEqual({ total: 0, running: 0, success: 0, error: 0 })
  })

  it('counts a mix of running/success/error with the correct total', () => {
    const tools: ToolActivity[] = [
      activity('e1', 'success'),
      activity('e2', 'success'),
      activity('e3', 'running'),
      activity('e4', 'error'),
    ]
    expect(summarizeTools(tools)).toEqual({ total: 4, running: 1, success: 2, error: 1 })
  })

  it('handles a single-status list (all running)', () => {
    const tools: ToolActivity[] = [
      activity('e1', 'running'),
      activity('e2', 'running'),
      activity('e3', 'running'),
    ]
    expect(summarizeTools(tools)).toEqual({ total: 3, running: 3, success: 0, error: 0 })
  })
})
