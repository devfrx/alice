/**
 * useGenerationState.ts — Reactive state for in-progress 3D generation.
 *
 * Surfaces a single computed flag derived from
 * {@link useChatStore.activeToolExecutions} that views can use to render
 * a placeholder while ``cad_generate`` / ``cad_generate_from_image`` are
 * running.
 */

import { computed, type ComputedRef } from 'vue'

import { useChatStore } from '../stores/chat'

/** Tool names that produce 3D models and benefit from a generation overlay. */
const CAD_TOOL_NAMES = new Set([
  'cad_generate',
  'cad_generate_from_image',
  'cad_generator_cad_generate',
  'cad_generator_cad_generate_from_image',
])

function normalizeCadToolName(toolName: string): CadGenerationInfo['toolName'] | null {
  if (toolName.endsWith('cad_generate_from_image')) return 'cad_generate_from_image'
  if (toolName.endsWith('cad_generate')) return 'cad_generate'
  return null
}

export interface CadGenerationInfo {
  toolName: 'cad_generate' | 'cad_generate_from_image'
  executionId: string
}

export interface UseGenerationState {
  /** Currently-running CAD generation, or ``null`` when idle. */
  cadGenerationInProgress: ComputedRef<CadGenerationInfo | null>
}

/**
 * Track CAD generation activity from the chat store.
 *
 * Returns a single computed describing the in-flight CAD tool execution.
 */
export function useGenerationState(): UseGenerationState {
  const chatStore = useChatStore()

  const cadGenerationInProgress = computed<CadGenerationInfo | null>(() => {
    const exec = chatStore.activeToolExecutions.find(
      (e) => CAD_TOOL_NAMES.has(e.toolName) && e.status === 'running',
    )
    if (!exec) return null
    const toolName = normalizeCadToolName(exec.toolName)
    if (!toolName) return null
    return {
      toolName,
      executionId: exec.executionId,
    }
  })

  return { cadGenerationInProgress }
}
