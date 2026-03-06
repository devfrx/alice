/**
 * WebSocket connection manager for the OMNIA backend.
 *
 * Provides typed event dispatching, automatic reconnection with
 * exponential back-off, and clean teardown via {@link disconnect}.
 */

/** Callback signature for all WebSocket events. */
type MessageHandler = (data: unknown) => void

/**
 * Manages a single WebSocket connection with:
 * - automatic reconnect (exponential back-off, configurable cap)
 * - typed event emitter (`on` / `off` / `emit`)
 * - JSON and binary send helpers
 */
export class WebSocketManager {
  private ws: WebSocket | null = null
  private readonly url: string
  private handlers: Map<string, MessageHandler[]> = new Map()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectDelay = 1000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false

  /** Backpressure: pending messages queued when WebSocket buffer is full. */
  private sendQueue: string[] = []
  /** Maximum bytes in the WebSocket send buffer before queuing. */
  private readonly bufferHighWaterMark = 1_048_576 // 1 MB
  /** Maximum queued messages — oldest are dropped when exceeded. */
  private readonly maxQueueSize = 100
  /** Timer for draining the send queue. */
  private drainTimer: ReturnType<typeof setTimeout> | null = null

  constructor(url: string = 'ws://localhost:8000/api/ws/chat') {
    this.url = url
  }

  // -----------------------------------------------------------------------
  // Connection lifecycle
  // -----------------------------------------------------------------------

  /** Open the WebSocket connection. Safe to call multiple times. */
  connect(): void {
    // Prevent duplicate connections
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.intentionalClose = false
    this.ws = new WebSocket(this.url)

    this.ws.onopen = (): void => {
      console.log('[OMNIA WS] Connected to', this.url)
      this.reconnectAttempts = 0
      this.emit('connected', null)
    }

    this.ws.onmessage = (event: MessageEvent): void => {
      try {
        const data = JSON.parse(event.data as string)
        this.emit(data.type ?? 'message', data)
      } catch {
        // Binary data (e.g. audio frames) — pass through raw
        this.emit('binary', event.data)
      }
    }

    this.ws.onclose = (): void => {
      console.log('[OMNIA WS] Disconnected')
      this.emit('disconnected', null)
      if (!this.intentionalClose) {
        this.attemptReconnect()
      }
    }

    this.ws.onerror = (error: Event): void => {
      console.error('[OMNIA WS] Error:', error)
      this.emit('error', error)
    }
  }

  /**
   * Close the connection permanently (no automatic reconnect).
   * Call {@link connect} again to re-establish.
   */
  disconnect(): void {
    this.intentionalClose = true
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.drainTimer !== null) {
      clearTimeout(this.drainTimer)
      this.drainTimer = null
    }
    this.sendQueue.length = 0
    this.reconnectAttempts = 0
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  /** Whether the underlying socket is currently open. */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  // -----------------------------------------------------------------------
  // Reconnection
  // -----------------------------------------------------------------------

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[OMNIA WS] Max reconnect attempts reached, will retry after delay')
      this.emit('reconnect_failed', null)
      // Reset and try again after a long delay (30s)
      this.reconnectAttempts = 0
      this.reconnectTimer = setTimeout(() => this.connect(), 30_000)
      return
    }

    this.reconnectAttempts++
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
    console.log(`[OMNIA WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  // -----------------------------------------------------------------------
  // Sending
  // -----------------------------------------------------------------------

  /** Send a JSON-serialisable payload with backpressure management. */
  send(data: unknown): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return

    const payload = typeof data === 'string' ? data : JSON.stringify(data)

    if (this.ws.bufferedAmount < this.bufferHighWaterMark) {
      this.ws.send(payload)
      return
    }

    // Buffer is full — queue the message
    console.warn(`[OMNIA WS] Backpressure: bufferedAmount=${this.ws.bufferedAmount}, queueing message`)
    if (this.sendQueue.length >= this.maxQueueSize) {
      this.sendQueue.shift() // drop oldest
      console.warn('[OMNIA WS] Queue full, dropping oldest message')
    }
    this.sendQueue.push(payload)
    this.scheduleDrain()
  }

  /** Schedule periodic queue draining until the buffer is clear. */
  private scheduleDrain(): void {
    if (this.drainTimer !== null) return
    this.drainTimer = setTimeout(() => this.drainQueue(), 50)
  }

  /** Flush queued messages when the send buffer has capacity. */
  private drainQueue(): void {
    this.drainTimer = null
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.sendQueue.length = 0
      return
    }

    while (this.sendQueue.length > 0 && this.ws.bufferedAmount < this.bufferHighWaterMark) {
      this.ws.send(this.sendQueue.shift()!)
    }

    if (this.sendQueue.length > 0) {
      this.scheduleDrain()
    }
  }

  // -----------------------------------------------------------------------
  // Event emitter
  // -----------------------------------------------------------------------

  /** Register a handler for `event`. */
  on(event: string, handler: MessageHandler): void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, [])
    }
    this.handlers.get(event)!.push(handler)
  }

  /** Remove a previously registered handler. */
  off(event: string, handler: MessageHandler): void {
    const list = this.handlers.get(event)
    if (!list) return
    const idx = list.indexOf(handler)
    if (idx !== -1) list.splice(idx, 1)
  }

  /** Dispatch an event to all registered handlers. */
  private emit(event: string, data: unknown): void {
    this.handlers.get(event)?.forEach((handler) => handler(data))
  }
}

/** Singleton instance used across the application. */
export const wsManager = new WebSocketManager()
