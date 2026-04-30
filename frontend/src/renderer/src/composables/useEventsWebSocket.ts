/**
 * Composable for the persistent events WebSocket connection.
 *
 * Connects to `/api/events/ws` on setup and dispatches incoming
 * events to the relevant Pinia stores. Handles reconnection
 * with exponential back-off.
 */

import { onScopeDispose, ref } from 'vue'
import { useCalendarStore } from '../stores/calendar'
import { useEmailStore } from '../stores/email'
import { useMcpStore } from '../stores/mcp'
import { useNotesStore } from '../stores/notes'
import { useArtifactsStore } from '../stores/artifacts'
import { useServicesStore } from '../stores/services'
import { BACKEND_HOST } from '../services/api'
const WS_URL = `${BACKEND_HOST.replace(/^http/, 'ws')}/api/events/ws`

export function useEventsWebSocket() {
  const isConnected = ref(false)
  const isError = ref(false)
  const calendarStore = useCalendarStore()
  const emailStore = useEmailStore()
  const mcpStore = useMcpStore()
  const notesStore = useNotesStore()
  const artifactsStore = useArtifactsStore()
  const servicesStore = useServicesStore()

  let ws: WebSocket | null = null
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
        if (data.type === 'calendar_changed') {
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

        // Handle note events (Phase 13)
        if (
          data.type === 'note.created' ||
          data.type === 'note.updated' ||
          data.type === 'note.deleted'
        ) {
          void notesStore.loadNotes()
          void notesStore.loadFolders()
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
