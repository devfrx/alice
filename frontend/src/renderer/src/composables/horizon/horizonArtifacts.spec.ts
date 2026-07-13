/** Tests for the pure artifact extraction (tool-message JSON → flat list). */
import { describe, it, expect } from 'vitest'

import { extractArtifacts } from './horizonArtifacts'

type Msg = { role: string; content: string }

const cad = (name: string): Msg => ({
  role: 'tool',
  content: JSON.stringify({ model_name: name, export_url: `/x/${name}.glb`, format: 'glb' })
})
const chart = (id: string): Msg => ({
  role: 'tool',
  content: JSON.stringify({
    chart_id: id,
    chart_url: `/c/${id}.json`,
    chart_type: 'bar',
    title: `Chart ${id}`,
    created_at: '2024-01-01T00:00:00Z'
  })
})
// WhiteboardPayload requires: board_id, title, board_url (for isWhiteboardPayload: board_id + board_url + title).
// conversation_id and created_at are required by the interface but not checked by the type guard.
const board = (id: string, rev: number): Msg => ({
  role: 'tool',
  content: JSON.stringify({
    board_id: id,
    title: `Board ${id}`,
    board_url: `/api/artifacts/${id}/content`,
    conversation_id: null,
    created_at: '2024-01-01T00:00:00Z',
    rev
  })
})

describe('extractArtifacts', () => {
  it('collects artifacts chronologically across kinds', () => {
    const out = extractArtifacts([cad('a'), chart('c1'), cad('b')])
    expect(out.map((a) => a.kind)).toEqual(['3d', 'chart', '3d'])
    expect(out[0].cad?.model_name).toBe('a')
    expect(out[1].chart?.chart_id).toBe('c1')
  })

  it('ignores non-tool roles and non-JSON content', () => {
    const out = extractArtifacts([
      {
        role: 'assistant',
        content: JSON.stringify({ model_name: 'x', export_url: 'u', format: 'glb' })
      },
      { role: 'tool', content: 'plain text' }
    ])
    expect(out).toEqual([])
  })

  it('dedupes whiteboards by board_id keeping the latest payload', () => {
    const out = extractArtifacts([board('w1', 1), chart('c1'), board('w1', 2)])
    expect(out).toHaveLength(2)
    expect(out[0].kind).toBe('whiteboard')
    expect((out[0].board as { rev?: number }).rev).toBe(2)
  })

  it('yields no artifact for a JSON tool message matching none of the three shapes', () => {
    const out = extractArtifacts([
      { role: 'tool', content: JSON.stringify({ some_field: 'value', other_field: 42 }) }
    ])
    expect(out).toEqual([])
  })
})
