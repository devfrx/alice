/** Types for the whiteboard (tldraw) system. Mirrors backend models. */

/** Full whiteboard spec including tldraw snapshot. */
export interface WhiteboardSpec {
  board_id: string
  title: string
  description: string
  conversation_id: string | null
  snapshot: Record<string, unknown>
  created_at: string
  updated_at: string
}

/** List item returned by GET /api/whiteboards. */
export interface WhiteboardListItem {
  board_id: string
  title: string
  description: string
  conversation_id: string | null
  created_at: string
  updated_at: string
  shape_count: number
}

/** Paginated list response from GET /api/whiteboards. */
export interface WhiteboardListResponse {
  items: WhiteboardListItem[]
  total: number
  limit: number
  offset: number
}

/** Response from PATCH /api/whiteboards/{id}/snapshot. */
export interface WhiteboardSnapshotUpdateResponse {
  status: string
  board_id: string
  updated_at: string | null
}
