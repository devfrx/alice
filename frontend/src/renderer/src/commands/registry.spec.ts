/** Unit tests for the Command Registry (vitest node env, no DOM). */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { CommandRegistry, CommandNotFoundError, DuplicateCommandError } from './registry'

let reg: CommandRegistry
beforeEach(() => {
  reg = new CommandRegistry()
})

describe('register/list', () => {
  it('registers and lists definitions in order', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    reg.register({ name: 'b.two', title: 'B', capability: 'mutate', run: () => 2 })
    expect(reg.list().map((d) => d.name)).toEqual(['a.one', 'b.two'])
    expect(reg.has('a.one')).toBe(true)
  })

  it('throws on duplicate names', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    expect(() =>
      reg.register({ name: 'a.one', title: 'A2', capability: 'read', run: () => 2 }),
    ).toThrow(DuplicateCommandError)
  })

  it('exposeToAgent defaults to undefined/false', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    expect(reg.list()[0].exposeToAgent ?? false).toBe(false)
  })
})

describe('execute', () => {
  it('runs the handler with args and returns its value', async () => {
    const run = vi.fn().mockResolvedValue('ok')
    reg.register({ name: 'x.y', title: 'X', capability: 'navigation', run })
    await expect(reg.execute('x.y', { k: 1 })).resolves.toBe('ok')
    expect(run).toHaveBeenCalledWith({ k: 1 })
  })

  it('throws CommandNotFoundError for unknown names', async () => {
    await expect(reg.execute('nope', {})).rejects.toThrow(CommandNotFoundError)
  })

  it('unregister removes the command', async () => {
    reg.register({ name: 'x.y', title: 'X', capability: 'navigation', run: () => 0 })
    reg.unregister('x.y')
    await expect(reg.execute('x.y', {})).rejects.toThrow(CommandNotFoundError)
  })
})
