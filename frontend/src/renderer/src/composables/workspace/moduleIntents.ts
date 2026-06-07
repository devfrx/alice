/**
 * moduleIntents.ts — Lightweight pub/sub bus for "open module" intents.
 *
 * Producers call `emitOpenModule` to request that the workspace open a
 * module. Consumers (the workspace store / panel host) register with
 * `onOpenModule` and react accordingly.
 *
 * No external dependency — a plain Set keeps it framework-agnostic and
 * import-cycle-free: any file can call `emitOpenModule` without importing
 * the workspace store.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OpenModuleIntent {
  /** The module identifier — must match a key in MODULE_REGISTRY. */
  moduleId: string
  /** Optional extra data forwarded to the module component as `params`. */
  params?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------------

type Handler = (intent: OpenModuleIntent) => void

const _handlers: Set<Handler> = new Set()

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Emit an intent to open `moduleId`.
 *
 * All currently-registered handlers are called synchronously in registration
 * order. Iteration runs over a snapshot copy of the set so a handler that
 * calls `unsubscribe` during dispatch does not corrupt the loop.
 */
export function emitOpenModule(moduleId: string, params?: Record<string, unknown>): void {
  const intent: OpenModuleIntent = { moduleId, params }
  // Snapshot — safe even if a handler unsubscribes itself mid-loop.
  const snapshot = Array.from(_handlers)
  for (const handler of snapshot) {
    handler(intent)
  }
}

/**
 * Register a handler for open-module intents.
 *
 * @returns An unsubscribe function. Call it (e.g. in `onUnmounted`) to
 *          deregister the handler and prevent memory leaks.
 */
export function onOpenModule(handler: Handler): () => void {
  _handlers.add(handler)
  return () => {
    _handlers.delete(handler)
  }
}

/**
 * Remove all registered handlers.
 *
 * Intended for use in tests only — keeps test cases isolated without
 * having to track individual unsubscribe calls.
 */
export function _clearOpenModuleHandlers(): void {
  _handlers.clear()
}
