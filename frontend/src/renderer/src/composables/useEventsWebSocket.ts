/**
 * Composable for the persistent events WebSocket connection.
 *
 * Connects to `/api/events/ws` on setup and dispatches incoming
 * events to the relevant Pinia stores. Handles reconnection
 * with exponential back-off.
 */

import { onScopeDispose, ref, type Ref } from 'vue'
import { useCalendarStore } from '../stores/calendar'
import { useEmailStore } from '../stores/email'
import { useMcpStore } from '../stores/mcp'
import { useArtifactsStore } from '../stores/artifacts'
import { useServicesStore } from '../stores/services'
import { useTasksStore } from '../stores/tasks'
import { usePlanDocumentStore } from '../stores/planDocument'
import { useScopeStore } from '../stores/scope'
import { usePermissionModeStore } from '../stores/permissionMode'
import { useTerminalSessionsStore } from '../stores/terminalSessions'
import type { EventsClientMessage, EventsServerMessage } from '../types/generated'
import { BACKEND_HOST } from '../services/api'

const WS_URL = `${BACKEND_HOST.replace(/^http/, 'ws')}/api/events/ws`

/**
 * Exhaustive map of events-WS frame types to handlers. Adding a frame to
 * the backend ws_schema and regenerating the contracts makes this object
 * FAIL TO COMPILE until the new frame is handled (or explicitly no-op'd).
 */
type EventsHandlerMap = {
  [K in EventsServerMessage['type']]: (msg: Extract<EventsServerMessage, { type: K }>) => void
}

/**
 * Module-level singleton socket. The events WS is connected exactly once (in
 * App.vue), so a module-scoped reference lets non-composable callers — notably
 * the terminal store — send control frames (`terminal.input` / `terminal.resize`)
 * over the same connection via {@link sendEventsMessage}.
 */
let ws: WebSocket | null = null

/**
 * Send a JSON frame over the events WebSocket if it is open.
 *
 * @returns `true` if the frame was sent, `false` when the socket is not open
 *   (the caller may drop the frame — terminal I/O is best-effort).
 */
export function sendEventsMessage(frame: EventsClientMessage): boolean {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(frame))
    return true
  }
  return false
}

export function useEventsWebSocket(): {
  isConnected: Ref<boolean>
  isError: Ref<boolean>
  connect: () => void
  disconnect: () => void
} {
  const isConnected = ref(false)
  const isError = ref(false)
  const calendarStore = useCalendarStore()
  const emailStore = useEmailStore()
  const mcpStore = useMcpStore()
  const artifactsStore = useArtifactsStore()
  const servicesStore = useServicesStore()
  const tasksStore = useTasksStore()
  const planDocumentStore = usePlanDocumentStore()
  const scopeStore = useScopeStore()
  const permissionModeStore = usePermissionModeStore()
  const terminalStore = useTerminalSessionsStore()

  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let intentionalClose = false
  let pingInterval: ReturnType<typeof setInterval> | null = null
  let megaCycles = 0
  const MAX_MEGA_CYCLES = 3

  const noop = (): void => {}
  const handlers: EventsHandlerMap = {
    pong: noop,
    heartbeat: noop,
    'calendar.changed': () => void calendarStore.refresh(),
    'mcp.server.connected': () => void mcpStore.loadServers(),
    'mcp.server.disconnected': () => void mcpStore.loadServers(),
    'email.received': (msg) => emailStore.handleEmailReceived(msg.folder ?? 'INBOX'),
    'email.sent': noop,
    'note.created': noop,
    'note.updated': noop,
    'note.deleted': noop,
    'service.status': (msg) => servicesStore.onServiceStatus(msg),
    'service.model_download_progress': (msg) => servicesStore.onDownloadProgress(msg),
    'knowledge.status': (msg) => servicesStore.onKnowledgeStatus(msg),
    'artifact.created': (msg) => void artifactsStore.fetchById(msg.artifact_id),
    'artifact.updated': (msg) => void artifactsStore.applyArtifactUpdated(msg.artifact_id),
    'artifact.deleted': (msg) => artifactsStore.removeLocal(msg.artifact_id),
    'artifact.bulk_deleted': (msg) =>
      artifactsStore.applyBulkDeleted(msg.conversation_id ?? null, msg.artifact_ids),
    'tasks.updated': (msg) => tasksStore.applyTasksUpdated(msg),
    'plan_document.updated': (msg) => planDocumentStore.applyPlanDocumentUpdated(msg),
    'scope.updated': (msg) => scopeStore.applyScopeUpdated(msg),
    'permission_mode.updated': (msg) => permissionModeStore.applyModeUpdated(msg),
    'config.changed': noop,
    'terminal.session_opened': (msg) => terminalStore.applySessionOpened(msg),
    'terminal.output': (msg) => terminalStore.applyOutput(msg),
    'terminal.closed': (msg) => terminalStore.applyClosed(msg),
    'terminal.renamed': (msg) => terminalStore.applyRenamed(msg),
    'terminal.assigned': (msg) => terminalStore.applyAssigned(msg)
  }

  function connect(): void {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    intentionalClose = false
    ws = new WebSocket(WS_URL)

    ws.onopen = (): void => {
      console.log('[ALICE Events WS] Connected')
      isConnected.value = true
      isError.value = false
      reconnectAttempts = 0
      megaCycles = 0

      // Send ping every 30s to keep connection alive
      pingInterval = setInterval(() => {
        sendEventsMessage({ type: 'ping' })
      }, 30_000)
    }

    ws.onmessage = (event: MessageEvent): void => {
      let data: EventsServerMessage
      try {
        data = JSON.parse(event.data as string) as EventsServerMessage
      } catch {
        console.warn('[ALICE Events WS] Failed to parse message')
        return
      }
      const handler = handlers[data.type] as ((msg: EventsServerMessage) => void) | undefined
      if (handler) {
        handler(data)
      } else {
        // Runtime safety net for frames newer than the bundled contract.
        console.warn('[ALICE Events WS] Unhandled frame type:', (data as { type?: string }).type)
      }
    }

    ws.onclose = (): void => {
      isConnected.value = false
      clearPing()
      if (!intentionalClose) {
        scheduleReconnect()
      }
    }

    ws.onerror = (): void => {
      isConnected.value = false
    }
  }

  function disconnect(): void {
    intentionalClose = true
    clearPing()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected.value = false
  }

  function clearPing(): void {
    if (pingInterval) {
      clearInterval(pingInterval)
      pingInterval = null
    }
  }

  function scheduleReconnect(): void {
    if (reconnectAttempts >= 10) {
      megaCycles++
      if (megaCycles >= MAX_MEGA_CYCLES) {
        console.error('[ALICE Events WS] Permanently failed after', megaCycles, 'cycles')
        isError.value = true
        return
      }
      reconnectAttempts = 0
      reconnectTimer = setTimeout(() => connect(), 30_000)
      return
    }
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30_000)
    reconnectAttempts += 1
    reconnectTimer = setTimeout(() => {
      connect()
    }, delay)
  }

  // Auto-connect only when autoConnect is not explicitly false.
  // App.vue defers connection until the backend is ready.
  onScopeDispose(() => disconnect())

  return { isConnected, isError, connect, disconnect }
}
