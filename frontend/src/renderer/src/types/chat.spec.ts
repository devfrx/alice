/**
 * chat.spec.ts
 *
 * Unit tests for the chart-extraction helpers in types/chat.ts.
 * These are pure functions (no Pinia / Vue reactivity required), so they are
 * exercised in isolation. The isChartPayload and extractCharts helpers are
 * tested exhaustively here.
 */
import { describe, it, expect } from 'vitest'
import { isChartPayload, extractCharts } from './chat'
import type { ChatMessage, ChartPayload } from './chat'

function toolMsg(id: string, content: string): ChatMessage {
  return {
    id,
    role: 'tool',
    content,
    tool_calls: null,
    tool_call_id: `tc-${id}`,
    created_at: '2026-06-07T00:00:00Z',
  } as ChatMessage
}

function chart(id: string): ChartPayload {
  return {
    chart_id: id,
    title: `Chart ${id}`,
    chart_type: 'bar',
    chart_url: `/api/charts/${id}`,
    created_at: '2026-06-07T00:00:00Z',
  }
}

describe('isChartPayload', () => {
  it('accepts a well-formed chart payload', () => {
    expect(isChartPayload(chart('a'))).toBe(true)
  })

  it('rejects null, arrays, and primitives', () => {
    expect(isChartPayload(null)).toBe(false)
    expect(isChartPayload(undefined)).toBe(false)
    expect(isChartPayload([chart('a')])).toBe(false)
    expect(isChartPayload('x')).toBe(false)
    expect(isChartPayload(42)).toBe(false)
  })

  it('rejects objects missing required string fields', () => {
    expect(isChartPayload({ chart_id: 'a', chart_url: '/u' })).toBe(false)
    expect(isChartPayload({ chart_id: 'a', chart_url: '/u', chart_type: 1 })).toBe(false)
    expect(isChartPayload({ chart_id: 1, chart_url: '/u', chart_type: 'bar' })).toBe(false)
  })
})

describe('extractCharts', () => {
  it('returns an empty list when there are no charts', () => {
    expect(extractCharts([])).toEqual([])
    expect(extractCharts([toolMsg('1', 'not json')])).toEqual([])
  })

  it('extracts only tool messages whose JSON is a chart payload', () => {
    const messages: ChatMessage[] = [
      { id: 'u', role: 'user', content: JSON.stringify(chart('skip-user')) } as ChatMessage,
      toolMsg('1', JSON.stringify(chart('c1'))),
      toolMsg('2', 'plain text result'),
      toolMsg('3', JSON.stringify({ board_id: 'wb1', kind: 'whiteboard' })),
      toolMsg('4', JSON.stringify(chart('c2'))),
    ]
    const result = extractCharts(messages)
    expect(result.map((c) => c.chart_id)).toEqual(['c1', 'c2'])
  })

  it('preserves chronological order (oldest → newest)', () => {
    const messages = [
      toolMsg('1', JSON.stringify(chart('first'))),
      toolMsg('2', JSON.stringify(chart('second'))),
      toolMsg('3', JSON.stringify(chart('third'))),
    ]
    const ids = extractCharts(messages).map((c) => c.chart_id)
    expect(ids).toEqual(['first', 'second', 'third'])
    // The most-recent chart is the last element.
    expect(ids[ids.length - 1]).toBe('third')
  })

  it('ignores malformed JSON without throwing', () => {
    const messages = [
      toolMsg('1', '{ broken json'),
      toolMsg('2', JSON.stringify(chart('ok'))),
    ]
    expect(extractCharts(messages).map((c) => c.chart_id)).toEqual(['ok'])
  })
})
