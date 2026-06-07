/**
 * useArtifactAutoOpen — PRODUCER composable.
 *
 * Watches for newly-arriving content (CAD artifacts, chart payloads,
 * whiteboard payloads) and emits open-module intents via the intent bus
 * so the workspace can auto-open the right module.
 *
 * Rules:
 * - Only reacts to content that arrives AFTER this composable mounts
 *   (seen-id Sets are pre-seeded with whatever exists at mount time).
 * - Never re-emits for the same id (dedup via Set).
 * - No-ops when `workspaceStore.autoOpenEnabled` is false.
 * - All watchers are automatically cleaned up when the owning component
 *   unmounts (Vue scope disposal).
 *
 * @param conversationIdRef - Reactive ref/getter for the active conversation id.
 *   Used to scope chart/whiteboard detection to the current conversation's
 *   messages.
 */

import { watch, type Ref } from 'vue'
import { useArtifactsStore } from '../../stores/artifacts'
import { useChatStore } from '../../stores/chat'
import { useWorkspaceStore } from '../../stores/workspace'
import { extractCharts } from '../../stores/charts'
import { emitOpenModule } from './moduleIntents'
import type { ChatMessage, ChartPayload } from '../../types/chat'
import { isWhiteboardPayload } from '../../types/chat'

// ---------------------------------------------------------------------------
// Pure helpers (also used in tests)
// ---------------------------------------------------------------------------

/**
 * Return true if `id` is NOT in `seen`. Does NOT mutate `seen`.
 * Call `seen.add(id)` separately after deciding to emit.
 */
export function isNewId(seen: Set<string>, id: string): boolean {
  return !seen.has(id)
}

/**
 * Given the current array of ids and a seen set, return ids that are present
 * in `current` but not yet in `seen`.
 */
export function diffNewIds(seen: Set<string>, current: string[]): string[] {
  return current.filter((id) => !seen.has(id))
}

// ---------------------------------------------------------------------------
// Payload extraction helpers
// ---------------------------------------------------------------------------

function extractChartIds(messages: ChatMessage[]): Map<string, ChartPayload> {
  const result = new Map<string, ChartPayload>()
  for (const payload of extractCharts(messages)) {
    result.set(payload.chart_id, payload)
  }
  return result
}

function extractBoardIds(messages: ChatMessage[]): Set<string> {
  const result = new Set<string>()
  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    try {
      const p = JSON.parse(msg.content) as unknown
      if (isWhiteboardPayload(p)) {
        result.add(p.board_id)
      }
    } catch {
      // not JSON — skip
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export function useArtifactAutoOpen(conversationIdRef?: Ref<string | null | undefined>): void {
  const artifactsStore = useArtifactsStore()
  const chatStore = useChatStore()
  const workspaceStore = useWorkspaceStore()

  // ── Seed seen-id sets from the current state at mount time ──────────────

  const seenArtifactIds = new Set<string>(
    artifactsStore.items
      .filter((a) => a.kind === 'cad_3d_text' || a.kind === 'cad_3d_image')
      .map((a) => a.id)
  )

  const initialMessages = chatStore.messages
  const seenChartIds = new Set<string>(extractChartIds(initialMessages).keys())
  const seenBoardIds = new Set<string>(extractBoardIds(initialMessages))

  // ── Watcher: new CAD artifacts ───────────────────────────────────────────

  watch(
    () => artifactsStore.items,
    (items) => {
      if (!workspaceStore.autoOpenEnabled) return
      for (const artifact of items) {
        if (artifact.kind !== 'cad_3d_text' && artifact.kind !== 'cad_3d_image') continue
        if (seenArtifactIds.has(artifact.id)) continue
        seenArtifactIds.add(artifact.id)
        // Only auto-open for the active conversation when a conversationId is provided
        if (conversationIdRef?.value && artifact.conversation_id !== conversationIdRef.value) {
          continue
        }
        emitOpenModule('cad3d', { artifactId: artifact.id })
      }
    },
    { deep: true }
  )

  // ── Watcher: new chart payloads in messages ──────────────────────────────

  watch(
    () => chatStore.messages,
    (messages) => {
      if (!workspaceStore.autoOpenEnabled) return
      const currentCharts = extractChartIds(messages)
      for (const [chartId, payload] of currentCharts) {
        if (seenChartIds.has(chartId)) continue
        seenChartIds.add(chartId)
        emitOpenModule('chart', { chartPayload: payload })
      }
    },
    { deep: false }
  )

  // ── Watcher: new whiteboard payloads in messages ─────────────────────────

  watch(
    () => chatStore.messages,
    (messages) => {
      if (!workspaceStore.autoOpenEnabled) return
      const currentBoards = extractBoardIds(messages)
      for (const boardId of currentBoards) {
        if (seenBoardIds.has(boardId)) continue
        seenBoardIds.add(boardId)
        emitOpenModule('whiteboard', { boardId })
      }
    },
    { deep: false }
  )
}
