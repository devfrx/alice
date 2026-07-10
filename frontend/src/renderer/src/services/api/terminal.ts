/** Interactive terminal session endpoints (`/api/terminal`). */
import { request } from './http'
import type {
  TerminalCreateRequest,
  TerminalListResponse,
  TerminalSession,
  TerminalUpdateRequest,
} from '../../types/terminal'

export const terminalApi = {
  /** List a conversation's live terminal sessions (+ the enabled flag). */
  listTerminals: (conversationId: string): Promise<TerminalListResponse> =>
    request<TerminalListResponse>(`/terminal/${encodeURIComponent(conversationId)}`),

  /** Open a new interactive terminal session (scope-confined). */
  createTerminal: (
    conversationId: string, body: TerminalCreateRequest = {},
  ): Promise<TerminalSession> =>
    request<TerminalSession>(`/terminal/${encodeURIComponent(conversationId)}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Rename and/or (re)assign a terminal session to the agent. */
  updateTerminal: (
    conversationId: string, sessionId: string, body: TerminalUpdateRequest,
  ): Promise<TerminalSession> =>
    request<TerminalSession>(
      `/terminal/${encodeURIComponent(conversationId)}/${encodeURIComponent(sessionId)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),

  /** Kill a terminal session (its whole process tree). */
  deleteTerminal: (
    conversationId: string, sessionId: string,
  ): Promise<void> =>
    request<void>(
      `/terminal/${encodeURIComponent(conversationId)}/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' },
    ),
}
