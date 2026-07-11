/**
 * Command Layer types (spec §7).
 *
 * Every UI capability is a named command with a typed handler and a
 * capability tag. In Fase 7 the registry's agent-exposable subset becomes the
 * manifest sent to the backend (`app_command` tool); `exposeToAgent` is the
 * structural anti-escalation seam: commands touching permission mode, scope,
 * allowlists or guardrail config MUST NEVER set it.
 */

/** What a command does to the app — used for permission-mode gating (Fase 7). */
export type CommandCapability = 'navigation' | 'read' | 'mutate' | 'destructive'

export interface CommandDefinition<A = Record<string, never>> {
  /** Unique dotted name, `domain.action` (e.g. `view.switch`). */
  name: string
  /** Human-readable label (command palette / audit). */
  title: string
  /**
   * Machine-facing description (English) for the agent manifest. Required
   * on every `exposeToAgent` command; `title` stays the human label.
   */
  description?: string
  capability: CommandCapability
  /**
   * Whether the command may appear in the agent-callable manifest (Fase 7).
   * Defaults to false; guardrail commands must never be exposable.
   */
  exposeToAgent?: boolean
  /** JSON-Schema-like description of `args` (feeds the Fase 7 manifest). */
  argsSchema?: Record<string, unknown>
  /** The single implementation of the capability. */
  run: (args: A) => Promise<unknown> | unknown
}
