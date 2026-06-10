/**
 * horizonArtifacts.ts — Pure extraction of presentable artifacts (3D models,
 * charts, whiteboards) from conversation tool messages. Lifted from the
 * retired orb-era assistant view computeds into one chronological flat list
 * that drives the Horizon stage carousel.
 */
import type { CadModelPayload, ChartPayload, WhiteboardPayload } from '../../types/chat'
import { isWhiteboardPayload } from '../../types/chat'

export type HorizonArtifactKind = '3d' | 'chart' | 'whiteboard'

export interface HorizonArtifact {
  kind: HorizonArtifactKind
  cad?: CadModelPayload
  chart?: ChartPayload
  board?: WhiteboardPayload
}

/** Mono shelf caption per artifact kind (editorial Italian). */
export function artifactLabel(kind: HorizonArtifactKind): string {
  switch (kind) {
    case '3d':
      return 'MODELLO'
    case 'chart':
      return 'GRAFICO'
    case 'whiteboard':
      return 'LAVAGNA'
  }
}

/** Minimal message shape needed for extraction (store-agnostic). */
export interface ArtifactSourceMessage {
  role: string
  content: string
}

/** Extract all artifacts in chronological order; whiteboards dedupe by board_id. */
export function extractArtifacts(messages: ArtifactSourceMessage[]): HorizonArtifact[] {
  const out: HorizonArtifact[] = []
  const boardSlots = new Map<string, number>()

  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    let p: unknown
    try {
      p = JSON.parse(msg.content)
    } catch {
      continue
    }
    if (typeof p !== 'object' || p === null) continue
    const obj = p as Record<string, unknown>

    if (typeof obj.model_name === 'string' && typeof obj.export_url === 'string') {
      out.push({ kind: '3d', cad: p as CadModelPayload })
    } else if (obj.chart_id && obj.chart_url && obj.chart_type) {
      out.push({ kind: 'chart', chart: p as ChartPayload })
    } else if (isWhiteboardPayload(p)) {
      const existing = boardSlots.get(p.board_id)
      if (existing !== undefined) {
        out[existing] = { kind: 'whiteboard', board: p }
      } else {
        boardSlots.set(p.board_id, out.length)
        out.push({ kind: 'whiteboard', board: p })
      }
    }
  }
  return out
}
