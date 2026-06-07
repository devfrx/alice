/**
 * moduleIntents.spec.ts
 *
 * Unit tests for the open-module intent pub/sub bus.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  emitOpenModule,
  onOpenModule,
  _clearOpenModuleHandlers,
  type OpenModuleIntent
} from './moduleIntents'

beforeEach(() => {
  _clearOpenModuleHandlers()
})

describe('emitOpenModule', () => {
  it('is a no-op when no handlers are registered', () => {
    expect(() => emitOpenModule('chart')).not.toThrow()
  })

  it('delivers the intent to a registered handler', () => {
    const received: OpenModuleIntent[] = []
    onOpenModule((intent) => received.push(intent))

    emitOpenModule('chart')

    expect(received).toHaveLength(1)
    expect(received[0].moduleId).toBe('chart')
  })

  it('forwards params through to the handler', () => {
    const received: OpenModuleIntent[] = []
    onOpenModule((intent) => received.push(intent))

    emitOpenModule('whiteboard', { artifactId: 'abc', zoom: 1.5 })

    expect(received[0].params).toEqual({ artifactId: 'abc', zoom: 1.5 })
  })

  it('delivers to multiple handlers in registration order', () => {
    const order: string[] = []
    onOpenModule(() => order.push('first'))
    onOpenModule(() => order.push('second'))

    emitOpenModule('cad3d')

    expect(order).toEqual(['first', 'second'])
  })

  it('does not include params key when none are provided', () => {
    const received: OpenModuleIntent[] = []
    onOpenModule((intent) => received.push(intent))

    emitOpenModule('chat')

    expect(received[0].params).toBeUndefined()
  })
})

describe('onOpenModule / unsubscribe', () => {
  it('stops delivering after unsubscribe is called', () => {
    const received: OpenModuleIntent[] = []
    const unsub = onOpenModule((intent) => received.push(intent))

    emitOpenModule('chart')
    expect(received).toHaveLength(1)

    unsub()
    emitOpenModule('chart')
    expect(received).toHaveLength(1) // still 1 — second emit not delivered
  })

  it('unsubscribing one handler does not affect others', () => {
    const a: OpenModuleIntent[] = []
    const b: OpenModuleIntent[] = []
    const unsubA = onOpenModule((intent) => a.push(intent))
    onOpenModule((intent) => b.push(intent))

    unsubA()
    emitOpenModule('chart')

    expect(a).toHaveLength(0)
    expect(b).toHaveLength(1)
  })

  it('a handler that unsubscribes mid-dispatch does not break iteration', () => {
    const delivered: string[] = []
    let unsub: (() => void) | null = null

    // First handler unsubscribes itself during the call
    unsub = onOpenModule(() => {
      delivered.push('self-unsub')
      unsub!()
    })

    // Second handler should still be called
    onOpenModule(() => delivered.push('stable'))

    expect(() => emitOpenModule('chart')).not.toThrow()
    expect(delivered).toContain('self-unsub')
    expect(delivered).toContain('stable')
  })

  it('after self-unsub the handler is not called on the next emit', () => {
    const count = vi.fn()
    let unsub: (() => void) | null = null
    unsub = onOpenModule(() => {
      count()
      unsub!()
    })

    emitOpenModule('chart')
    emitOpenModule('chart')

    expect(count).toHaveBeenCalledTimes(1)
  })
})

describe('_clearOpenModuleHandlers', () => {
  it('removes all handlers so subsequent emits are silent', () => {
    const received: OpenModuleIntent[] = []
    onOpenModule((intent) => received.push(intent))

    _clearOpenModuleHandlers()
    emitOpenModule('chart')

    expect(received).toHaveLength(0)
  })
})

describe('MODULE_REGISTRY shape', () => {
  // Optional registry shape tests co-located here for convenience.
  it('module registry has the four expected ids', async () => {
    const { MODULE_REGISTRY } = await import('./moduleRegistry')

    expect(Object.keys(MODULE_REGISTRY)).toEqual(
      expect.arrayContaining(['chat', 'chart', 'whiteboard', 'cad3d'])
    )
    expect(Object.keys(MODULE_REGISTRY)).toHaveLength(4)
  })

  it('each entry has a non-empty label and a function component', async () => {
    const { MODULE_REGISTRY } = await import('./moduleRegistry')

    for (const [id, def] of Object.entries(MODULE_REGISTRY)) {
      expect(def.id).toBe(id)
      expect(typeof def.label).toBe('string')
      expect(def.label.length).toBeGreaterThan(0)
      expect(typeof def.component).toBe('function')
    }
  })

  it('isModuleRegistered returns true for known ids and false for unknown', async () => {
    const { isModuleRegistered } = await import('./moduleRegistry')

    expect(isModuleRegistered('chat')).toBe(true)
    expect(isModuleRegistered('chart')).toBe(true)
    expect(isModuleRegistered('whiteboard')).toBe(true)
    expect(isModuleRegistered('cad3d')).toBe(true)
    expect(isModuleRegistered('nonexistent')).toBe(false)
    expect(isModuleRegistered('')).toBe(false)
  })

  it('listModules returns all four defs', async () => {
    const { listModules } = await import('./moduleRegistry')

    const modules = listModules()
    expect(modules).toHaveLength(4)
    expect(modules.map((m) => m.id).sort()).toEqual(['cad3d', 'chart', 'chat', 'whiteboard'])
  })
})
