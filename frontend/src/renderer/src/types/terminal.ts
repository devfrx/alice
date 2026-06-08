/**
 * terminal.ts — Types for the interactive PTY terminal (Fase 7 E1/E2).
 *
 * A conversation can own several live terminal sessions; exactly one may be
 * *assigned to the agent* (where `run_terminal_command` runs and mirrors its
 * output). The backend exposes them at `/api/terminal/{conversation_id}`:
 *
 * - REST: `GET` (list + enabled flag), `POST` (open), `PATCH` (rename/assign),
 *   `DELETE` (kill — process tree). None are idle-guarded.
 * - Live output is pushed on the events WebSocket as {@link WsTerminalOutput};
 *   input/resize travel back over the same socket as `terminal.input` /
 *   `terminal.resize` control frames.
 */

/** A single live terminal session (mirrors the backend snapshot). */
export interface TerminalSession {
  id: string
  conversation_id: string
  title: string
  cwd: string
  rows: number
  cols: number
  agent_assigned: boolean
  created_at: string
  pid: number | null
  alive: boolean
}

/** Response of `GET /api/terminal/{conversation_id}`. */
export interface TerminalListResponse {
  /** Whether the terminal capability is enabled in backend config. */
  enabled: boolean
  sessions: TerminalSession[]
}

/** Body for `POST /api/terminal/{conversation_id}`. */
export interface TerminalCreateRequest {
  cwd?: string
  title?: string
  rows?: number
  cols?: number
  assign_to_agent?: boolean
}

/** Body for `PATCH /api/terminal/{conversation_id}/{session_id}`. */
export interface TerminalUpdateRequest {
  title?: string
  assign_to_agent?: boolean
}

// --- Events-WS frames (server → client) ------------------------------------

export interface WsTerminalSessionOpenedMessage {
  type: 'terminal.session_opened'
  conversation_id: string
  session: TerminalSession
}

export interface WsTerminalOutputMessage {
  type: 'terminal.output'
  conversation_id: string
  session_id: string
  data: string
}

export interface WsTerminalClosedMessage {
  type: 'terminal.closed'
  conversation_id: string
  session_id: string
  exit_code: number | null
}

export interface WsTerminalRenamedMessage {
  type: 'terminal.renamed'
  conversation_id: string
  session_id: string
  title: string
}

export interface WsTerminalAssignedMessage {
  type: 'terminal.assigned'
  conversation_id: string
  session_id: string
}

// --- Control frames (client → server, over the events WS) ------------------

export interface WsTerminalInputFrame {
  type: 'terminal.input'
  conversation_id: string
  session_id: string
  data: string
}

export interface WsTerminalResizeFrame {
  type: 'terminal.resize'
  conversation_id: string
  session_id: string
  rows: number
  cols: number
}
