import { afterEach, describe, expect, it } from 'vitest'
import { commandRegistry } from './registry'
import { buildCommandManifest, handleCommandRequest, sendCommandManifest } from './bridge'
import type { EventsClientMessage, WsCommandRequest } from '../types/generated'

function makeSender(): {
  frames: EventsClientMessage[]
  send: (f: EventsClientMessage) => boolean
} {
  const frames: EventsClientMessage[] = []
  return {
    frames,
    send: (f) => {
      frames.push(f)
      return true
    }
  }
}

function request(name: string, args: Record<string, unknown> = {}): WsCommandRequest {
  return {
    type: 'command.request',
    correlation_id: 'c-1',
    name,
    args
  } as WsCommandRequest
}

type CommandResultFrame = Extract<EventsClientMessage, { type: 'command.result' }>

afterEach(() => commandRegistry.clear())

describe('buildCommandManifest', () => {
  it('projects only exposeToAgent commands with description fallback', () => {
    commandRegistry.register({
      name: 'a.exposed',
      title: 'Titolo umano',
      capability: 'navigation',
      exposeToAgent: true,
      run: () => 1
    })
    commandRegistry.register({
      name: 'b.hidden',
      title: 'B',
      capability: 'mutate',
      run: () => 2
    })
    const manifest = buildCommandManifest()
    expect(manifest).toHaveLength(1)
    expect(manifest[0].name).toBe('a.exposed')
    expect(manifest[0].description).toBe('Titolo umano')
    expect(manifest[0].capability).toBe('navigation')
  })
})

describe('sendCommandManifest', () => {
  it('sends a command.manifest frame', () => {
    const { frames, send } = makeSender()
    expect(sendCommandManifest(send)).toBe(true)
    expect(frames[0].type).toBe('command.manifest')
  })
})

describe('handleCommandRequest', () => {
  it('executes an exposed command and replies ok with the correlation id', async () => {
    commandRegistry.register<{ x: number }>({
      name: 'a.run',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      argsSchema: { type: 'object', properties: { x: { type: 'number' } }, required: ['x'] },
      run: ({ x }) => x * 2
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.run', { x: 21 }), send)
    expect(frames).toHaveLength(1)
    const reply = frames[0] as CommandResultFrame
    expect(reply.type).toBe('command.result')
    expect(reply.correlation_id).toBe('c-1')
    expect(reply.ok).toBe(true)
    expect(reply.result).toBe(42)
  })

  it('refuses a non-exposed command (structural anti-escalation)', async () => {
    let ran = false
    commandRegistry.register({
      name: 'guard.only',
      title: 'G',
      capability: 'mutate',
      run: () => {
        ran = true
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('guard.only'), send)
    const reply = frames[0] as CommandResultFrame
    expect(ran).toBe(false)
    expect(reply.ok).toBe(false)
    expect(reply.error).toMatch(/not agent-callable/)
  })

  it('refuses an unknown command', async () => {
    const { frames, send } = makeSender()
    await handleCommandRequest(request('ghost.cmd'), send)
    const reply = frames[0] as CommandResultFrame
    expect(reply.ok).toBe(false)
  })

  it('rejects invalid args before executing', async () => {
    let ran = false
    commandRegistry.register({
      name: 'a.strict',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      argsSchema: { type: 'object', properties: { v: { type: 'string' } }, required: ['v'] },
      run: () => {
        ran = true
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.strict', { v: 5 }), send)
    const reply = frames[0] as CommandResultFrame
    expect(ran).toBe(false)
    expect(reply.ok).toBe(false)
    expect(reply.error).toMatch(/must be a string/)
  })

  it('maps a throwing command to a clean error reply', async () => {
    commandRegistry.register({
      name: 'a.boom',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      run: () => {
        throw new Error('boom')
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.boom'), send)
    const reply = frames[0] as CommandResultFrame
    expect(reply.ok).toBe(false)
    expect(reply.error).toBe('boom')
  })
})
