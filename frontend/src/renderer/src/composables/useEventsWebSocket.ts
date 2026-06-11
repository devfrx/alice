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
import type { WsTasksUpdatedMessage } from '../types/tasks'
import { usePlanDocumentStore } from '../stores/planDocument'
import type { WsPlanDocumentUpdatedMessage } from '../types/planDocument'
import { useScopeStore } from '../stores/scope'
import type { WsScopeUpdatedMessage } from '../types/scope'
import { usePermissionModeStore } from '../stores/permissionMode'
import type { WsPermissionModeUpdatedMessage } from '../types/permission'
import { useTerminalSessionsStore } from '../stores/terminalSessions'
import type {
  WsTerminalAssignedMessage,
  WsTerminalClosedMessage,
  WsTerminalOutputMessage,
  WsTerminalRenamedMessage,
  WsTerminalSessionOpenedMessage,
} from '../types/terminal'
import { BACKEND_HOST } from '../services/api'
const WS_URL = `${BACKEND_HOST.replace(/^http/, 'ws')}/api/events/ws`

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
export function sendEventsMessage(frame: Record<string, unknown>): boolean {
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
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30_000)
    }

    ws.onmessage = (event: MessageEvent): void => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'pong' || data.type === 'heartbeat') {
          return // Keep-alive, ignore
        }

        // Forward calendar change events to the store
        if (data.type === 'calendar.changed') {
          void calendarStore.refresh()
        }

        // Refresh MCP state on server connect/disconnect
        if (
          data.type === 'mcp.server.connected' ||
          data.type === 'mcp.server.disconnected'
        ) {
          void mcpStore.loadServers()
        }

        // Handle email events (Phase 15)
        if (data.type === 'email.received' && typeof data.folder === 'string') {
          emailStore.handleEmailReceived(data.folder as string)
        }

        // Handle artifact events: lazy-fetch the new artifact and add to store.
        if (data.type === 'artifact.created' && typeof data.artifact_id === 'string') {
          void artifactsStore.fetchById(data.artifact_id as string)
        }

        // Handle Service Orchestrator events (Phase 1 finalisation).
        if (data.type === 'service.status') {
          servicesStore.onServiceStatus(data)
        }
        if (data.type === 'service.model_download_progress') {
          servicesStore.onDownloadProgress(data)
        }

        // Knowledge/RAG readiness changes (e.g. after a vector-store repair).
        if (data.type === 'knowledge.status') {
          servicesStore.onKnowledgeStatus(data)
        }

        // Handle task updates: fold the full pushed step list into the store.
        if (data.type === 'tasks.updated' && typeof data.conversation_id === 'string') {
          tasksStore.applyTasksUpdated(data as WsTasksUpdatedMessage)
        }

        // Handle plan-document updates: fold the pushed markdown doc into the store.
        if (data.type === 'plan_document.updated' && typeof data.conversation_id === 'string') {
          planDocumentStore.applyPlanDocumentUpdated(data as WsPlanDocumentUpdatedMessage)
        }

        // Handle scope updates: fold the full pushed folder list into the store.
        if (data.type === 'scope.updated' && typeof data.conversation_id === 'string') {
          scopeStore.applyScopeUpdated(data as WsScopeUpdatedMessage)
        }

        // Handle permission-tier updates: fold the pushed tier into the store.
        if (data.type === 'permission_mode.updated' && typeof data.conversation_id === 'string') {
          permissionModeStore.applyModeUpdated(data as WsPermissionModeUpdatedMessage)
        }

        // Handle interactive-terminal lifecycle + output frames.
        if (data.type === 'terminal.output') {
          terminalStore.applyOutput(data as WsTerminalOutputMessage)
        } else if (data.type === 'terminal.session_opened') {
          terminalStore.applySessionOpened(data as WsTerminalSessionOpenedMessage)
        } else if (data.type === 'terminal.closed') {
          terminalStore.applyClosed(data as WsTerminalClosedMessage)
        } else if (data.type === 'terminal.renamed') {
          terminalStore.applyRenamed(data as WsTerminalRenamedMessage)
        } else if (data.type === 'terminal.assigned') {
          terminalStore.applyAssigned(data as WsTerminalAssignedMessage)
        }
      } catch {
        console.warn('[ALICE Events WS] Failed to parse message')
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
