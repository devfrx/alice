/**
 * Command Bridge (Fase 7, spec §7) — frontend side of the app_command RPC.
 *
 * Builds the agent-exposable manifest from the Command Registry and executes
 * `command.request` frames from the events WS, replying with `command.result`
 * (correlation_id echoed verbatim). STRUCTURAL anti-escalation: ONLY commands
 * with `exposeToAgent === true` are declared in the manifest AND executable
 * on the agent's behalf — the double check makes a forged request for a
 * guardrail command a clean error, not an execution.
 *
 * The frame sender is injected (instead of importing `sendEventsMessage`) to
 * avoid a module cycle with `useEventsWebSocket` and keep this unit testable.
 */
import { commandRegistry } from './registry'
import { validateCommandArgs } from './validate'
import type {
  CommandManifestEntry,
  EventsClientMessage,
  WsCommandRequest
} from '../types/generated'

export type SendFrame = (frame: EventsClientMessage) => boolean

/** Manifest projection of the registry: exposeToAgent commands only. */
export function buildCommandManifest(): CommandManifestEntry[] {
  return commandRegistry
    .list()
    .filter((def) => def.exposeToAgent === true)
    .map((def) => ({
      name: def.name,
      description: def.description ?? def.title,
      capability: def.capability,
      args_schema: def.argsSchema ?? { type: 'object', properties: {} }
    }))
}

/**
 * Send the current manifest to the backend (on WS open and on changes).
 *
 * NB: the registry has no change-notification hook yet — the exposed set is
 * static after install, so `onopen` is the only caller. The first dynamic
 * registration of an exposed command MUST call this too (backlog seam).
 */
export function sendCommandManifest(send: SendFrame): boolean {
  return send({ type: 'command.manifest', commands: buildCommandManifest() })
}

/** Execute a backend `command.request` and reply with `command.result`. */
export async function handleCommandRequest(msg: WsCommandRequest, send: SendFrame): Promise<void> {
  const reply = (ok: boolean, result?: unknown, error?: string): void => {
    const sent = send({
      type: 'command.result',
      correlation_id: msg.correlation_id,
      ok,
      result: result ?? null,
      error: error ?? null
    })
    if (!sent) {
      // The backend recovers via its RPC timeout; log so the drop is diagnosable.
      console.warn('[Command Bridge] reply dropped (socket closed):', msg.correlation_id)
    }
  }
  const def = commandRegistry.list().find((d) => d.name === msg.name)
  if (!def || def.exposeToAgent !== true) {
    reply(false, undefined, `Command not agent-callable: ${msg.name}`)
    return
  }
  const args = (msg.args ?? {}) as Record<string, unknown>
  // Validate against the SAME fallback the manifest advertises: a schema-less
  // exposed command is declared as "no args" and must reject any arg.
  const validationError = validateCommandArgs(
    def.argsSchema ?? { type: 'object', properties: {} },
    args
  )
  if (validationError) {
    reply(false, undefined, validationError)
    return
  }
  try {
    const result = await commandRegistry.execute(msg.name, args)
    reply(true, result ?? null)
  } catch (err) {
    reply(false, undefined, err instanceof Error ? err.message : String(err))
  }
}
