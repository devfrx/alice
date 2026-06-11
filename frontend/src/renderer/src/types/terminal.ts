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

import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type TerminalSession = ApiSchema<'WsTerminalSession'>

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
export type WsTerminalSessionOpenedMessage = ApiSchema<'WsTerminalSessionOpened'>
export type WsTerminalOutputMessage = ApiSchema<'WsTerminalOutput'>
export type WsTerminalClosedMessage = ApiSchema<'WsTerminalClosed'>
export type WsTerminalRenamedMessage = ApiSchema<'WsTerminalRenamed'>
export type WsTerminalAssignedMessage = ApiSchema<'WsTerminalAssigned'>

// --- Control frames (client → server, over the events WS) ------------------
export type WsTerminalInputFrame = ApiSchema<'WsTerminalInput'>
export type WsTerminalResizeFrame = ApiSchema<'WsTerminalResize'>
