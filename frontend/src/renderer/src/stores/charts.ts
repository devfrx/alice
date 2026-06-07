/**
 * charts.ts — Pinia setup-store for charts produced in the active conversation.
 *
 * Charts are not persisted as artifacts; the backend embeds each generated
 * chart as a JSON tool message ({@link ChartPayload}) in the conversation.
 * This store derives the chart list reactively from the chat store so a
 * workspace ChartModule tile can resolve a chart to display even when it was
 * opened without (or with a stale) `chartPayload` param — mirroring the
 * store-backed fallback that {@link useWhiteboardStore} (`currentBoard`) and
 * the artifacts store (`items`) give the whiteboard and 3D modules.
 */

import { defineStore } from 'pinia'
import { computed } from 'vue'

import { useChatStore } from './chat'
import type { ChatMessage, ChartPayload } from '../types/chat'

/**
 * Type guard: is `p` a {@link ChartPayload}?
 *
 * Mirrors the inline checks in MessageBubble / ChartModule so all three sites
 * agree on what counts as a chart payload.
 */
export function isChartPayload(p: unknown): p is ChartPayload {
  if (typeof p !== 'object' || p === null || Array.isArray(p)) return false
  const o = p as Record<string, unknown>
  return (
    typeof o.chart_id === 'string' &&
    typeof o.chart_url === 'string' &&
    typeof o.chart_type === 'string'
  )
}

/**
 * Extract every chart payload from a message list, in chronological order
 * (oldest → newest). Non-tool / non-JSON / non-chart messages are skipped.
 */
export function extractCharts(messages: ChatMessage[]): ChartPayload[] {
  const out: ChartPayload[] = []
  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    try {
      const p = JSON.parse(msg.content) as unknown
      if (isChartPayload(p)) out.push(p)
    } catch {
      // not JSON — skip
    }
  }
  return out
}

export const useChartsStore = defineStore('charts', () => {
  const chatStore = useChatStore()

  /** Charts in the active conversation, oldest → newest. */
  const charts = computed<ChartPayload[]>(() => extractCharts(chatStore.messages))

  /**
   * The most-recent chart in the active conversation, or null. Used as the
   * fallback content for a ChartModule tile opened without an explicit payload.
   */
  const currentChart = computed<ChartPayload | null>(() => {
    const list = charts.value
    return list.length > 0 ? list[list.length - 1] : null
  })

  /** Look up a chart by its id within the active conversation. */
  function findById(id: string): ChartPayload | null {
    return charts.value.find((c) => c.chart_id === id) ?? null
  }

  return {
    // getters
    charts,
    currentChart,
    // lookups
    findById,
  }
})
