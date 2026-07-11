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
import { usePlanDocumentStore } from '../../stores/planDocument'
import { emitOpenModule } from './moduleIntents'
import type { ChatMessage, ChartPayload } from '../../types/chat'
import { extractCharts, isWhiteboardPayload } from '../../types/chat'

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
  const planDocumentStore = usePlanDocumentStore()

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
  //
  // `chatStore.messages` switches wholesale when the active conversation
  // changes.  Without a guard, every chart already present in the
  // newly-opened conversation would look "new" and auto-open a tile on mere
  // navigation.  Track the conversation the seen-set belongs to and, on a
  // switch, re-baseline (seed the new conversation's existing charts as
  // already-seen) instead of emitting.  Re-baselining runs even when
  // auto-open is disabled so a later toggle never replays the backlog.

  let lastChartConvId = conversationIdRef?.value ?? null

  watch(
    () => chatStore.messages,
    (messages) => {
      const convId = conversationIdRef?.value ?? null
      const currentCharts = extractChartIds(messages)
      if (convId !== lastChartConvId) {
        lastChartConvId = convId
        seenChartIds.clear()
        for (const id of currentCharts.keys()) seenChartIds.add(id)
        return
      }
      if (!workspaceStore.autoOpenEnabled) return
      for (const [chartId, payload] of currentCharts) {
        if (seenChartIds.has(chartId)) continue
        seenChartIds.add(chartId)
        emitOpenModule('chart', { chartPayload: payload })
      }
    },
    { deep: false }
  )

  // ── Watcher: new whiteboard payloads in messages ─────────────────────────
  // Same conversation-switch re-baseline as the chart watcher above.

  let lastBoardConvId = conversationIdRef?.value ?? null

  watch(
    () => chatStore.messages,
    (messages) => {
      const convId = conversationIdRef?.value ?? null
      const currentBoards = extractBoardIds(messages)
      if (convId !== lastBoardConvId) {
        lastBoardConvId = convId
        seenBoardIds.clear()
        for (const boardId of currentBoards) seenBoardIds.add(boardId)
        return
      }
      if (!workspaceStore.autoOpenEnabled) return
      for (const boardId of currentBoards) {
        if (seenBoardIds.has(boardId)) continue
        seenBoardIds.add(boardId)
        emitOpenModule('whiteboard', { boardId })
      }
    },
    { deep: false }
  )

  // ── Watcher: plan document written/updated ───────────────────────────────
  // The agent's `write_plan` replaces the living plan doc; every change should
  // auto-open / foreground the plan module. Re-baseline on conversation switch
  // (same guard as the chart/board watchers) so mere navigation never opens it.

  const stampFor = (): string | null => {
    const id = conversationIdRef?.value ?? null
    return id ? (planDocumentStore.documentFor(id)?.updatedAt ?? null) : null
  }
  let lastPlanConvId = conversationIdRef?.value ?? null
  let lastPlanStamp = stampFor()

  watch(stampFor, (stamp) => {
    const convId = conversationIdRef?.value ?? null
    if (convId !== lastPlanConvId) {
      lastPlanConvId = convId
      lastPlanStamp = stamp
      return
    }
    if (stamp === lastPlanStamp) return
    lastPlanStamp = stamp
    if (!stamp) return
    if (!workspaceStore.autoOpenEnabled) return
    emitOpenModule('plan')
  })
}
