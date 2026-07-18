/**
 * useGenerationState.ts — Reactive state for in-progress 3D generation.
 *
 * Surfaces a single computed derived from the current run's tool activities
 * (the ``agentRun`` fold, spec §5) that views can use to render a placeholder
 * while ``cad_generate`` / ``cad_generate_from_image`` are running.
 */

import { computed, type ComputedRef } from 'vue'

import { useAgentRunStore } from '../stores/agentRun'
import type { ToolProgressSnapshot } from '../types/chat'

function normalizeCadToolName(toolName: string): CadGenerationInfo['toolName'] | null {
  if (toolName.endsWith('cad_generate_from_image')) return 'cad_generate_from_image'
  if (toolName.endsWith('cad_generate')) return 'cad_generate'
  return null
}

/**
 * Coerce a raw `tool.progress` payload (the tool's own nested dict, stored
 * verbatim on the fold) into the typed {@link ToolProgressSnapshot} the
 * placeholder consumes. Keys are the backend's snake_case
 * (``phase``/``label``/``step``/``total``/``percent``/``elapsed_s``).
 */
function coerceProgress(
  raw: Record<string, unknown> | undefined
): ToolProgressSnapshot | undefined {
  if (!raw) return undefined
  const asNum = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)
  return {
    phase: typeof raw.phase === 'string' ? raw.phase : undefined,
    label: typeof raw.label === 'string' ? raw.label : null,
    step: asNum(raw.step),
    total: asNum(raw.total),
    percent: asNum(raw.percent),
    elapsedS: asNum(raw.elapsed_s)
  }
}

export interface CadGenerationInfo {
  toolName: 'cad_generate' | 'cad_generate_from_image'
  executionId: string
  /** Latest progress snapshot, when the backend reports incremental updates. */
  progress?: ToolProgressSnapshot
}

export interface UseGenerationState {
  /** Currently-running CAD generation, or ``null`` when idle. */
  cadGenerationInProgress: ComputedRef<CadGenerationInfo | null>
}

/**
 * Track CAD generation activity from the current agent run.
 *
 * Returns a single computed describing the in-flight CAD tool execution.
 */
export function useGenerationState(): UseGenerationState {
  const agentRun = useAgentRunStore()

  const cadGenerationInProgress = computed<CadGenerationInfo | null>(() => {
    const tools = agentRun.currentRun?.tools ?? []
    const tool = tools.find(
      (t) => t.status === 'running' && normalizeCadToolName(t.toolName) !== null
    )
    if (!tool) return null
    const toolName = normalizeCadToolName(tool.toolName)
    if (!toolName) return null
    return {
      toolName,
      executionId: tool.executionId,
      progress: coerceProgress(tool.progress)
    }
  })

  return { cadGenerationInProgress }
}
