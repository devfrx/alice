/**
 * Frontend Command Registry (spec §7) — single registration point for UI
 * commands. UI call sites and (from Fase 7) the agent bridge execute the
 * SAME commands: one implementation per capability.
 */
import type { CommandDefinition } from './types'

export class CommandNotFoundError extends Error {
  constructor(name: string) {
    super(`Command not registered: ${name}`)
    this.name = 'CommandNotFoundError'
  }
}

export class DuplicateCommandError extends Error {
  constructor(name: string) {
    super(`Command already registered: ${name}`)
    this.name = 'DuplicateCommandError'
  }
}

export class CommandRegistry {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- heterogeneous arg shapes live in one map; typing is at the register/execute seam
  private commands = new Map<string, CommandDefinition<any>>()

  /** Register a command. Throws {@link DuplicateCommandError} on name reuse. */
  register<A>(def: CommandDefinition<A>): void {
    if (this.commands.has(def.name)) throw new DuplicateCommandError(def.name)
    this.commands.set(def.name, def)
  }

  /** Remove a command (no-op if absent). */
  unregister(name: string): void {
    this.commands.delete(name)
  }

  has(name: string): boolean {
    return this.commands.has(name)
  }

  /** Snapshot of all registered definitions (stable order of registration). */
  list(): CommandDefinition<unknown>[] {
    return [...this.commands.values()]
  }

  /** Execute a command by name. Throws {@link CommandNotFoundError} if absent. */
  async execute<A>(name: string, args: A): Promise<unknown> {
    const def = this.commands.get(name)
    if (!def) throw new CommandNotFoundError(name)
    return await def.run(args)
  }

  /** Test helper: drop every registration. */
  clear(): void {
    this.commands.clear()
  }
}

/** App-wide singleton registry. */
export const commandRegistry = new CommandRegistry()
