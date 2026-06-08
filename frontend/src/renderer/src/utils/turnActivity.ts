/**
 * turnActivity — Pure derivations over a turn's tool-activity list.
 *
 * Operates on the camelCase {@link ToolActivity} view-models folded by the
 * `agentRun` Pinia store (see `types/turn.ts`). Side-effect-free: safe to call
 * from `computed` / templates without touching reactive state.
 */

import type { ToolActivity } from '../types/turn'

/** Per-status counts for a run's tool activities. */
export interface ToolStatusSummary {
  /** Total number of tool activities. */
  total: number
  /** Activities still in flight. */
  running: number
  /** Activities that completed successfully. */
  success: number
  /** Activities that ended in error. */
  error: number
}

/**
 * Bucket a tool-activity list by lifecycle status.
 *
 * @param tools - The run's tool activities, in any order.
 * @returns Per-status counts plus the total. All zeros for an empty list.
 */
export function summarizeTools(tools: ToolActivity[]): ToolStatusSummary {
  const summary: ToolStatusSummary = {
    total: tools.length,
    running: 0,
    success: 0,
    error: 0,
  }
  for (const tool of tools) {
    if (tool.status === 'running') summary.running += 1
    else if (tool.status === 'success') summary.success += 1
    else if (tool.status === 'error') summary.error += 1
  }
  return summary
}
