/**
 * Unit tests for stores/terminalSessions.ts (Fase 7 E1).
 *
 * Pure Pinia store tests (vitest node env). The store keys live PTY sessions by
 * conversation, fetches the REST snapshot once, folds the `terminal.*` events,
 * buffers output for reattach, and pushes live chunks to subscribers. The REST
 * client and the events-WS singleton are mocked.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useTerminalSessionsStore } from './terminalSessions'
import { terminalApi } from '../services/api'
import { sendEventsMessage } from '../composables/useEventsWebSocket'
import type { TerminalSession } from '../types/terminal'

vi.mock('../services/api', () => ({
  terminalApi: {
    listTerminals: vi.fn(),
    createTerminal: vi.fn(),
    updateTerminal: vi.fn(),
    deleteTerminal: vi.fn()
  }
}))

vi.mock('../composables/useEventsWebSocket', () => ({
  sendEventsMessage: vi.fn(() => true)
}))

const listMock = vi.mocked(terminalApi.listTerminals)
const createMock = vi.mocked(terminalApi.createTerminal)
const deleteMock = vi.mocked(terminalApi.deleteTerminal)
const sendMock = vi.mocked(sendEventsMessage)

const CONV = 'c1'

function sess(id: string, over: Partial<TerminalSession> = {}): TerminalSession {
  return {
    id,
    conversation_id: CONV,
    title: `Terminal ${id}`,
    cwd: 'C:/work',
    rows: 24,
    cols: 80,
    agent_assigned: false,
    created_at: '2026-06-09T00:00:00Z',
    pid: 100,
    alive: true,
    ...over
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('terminalSessions store', () => {
  it('fetches once and exposes the enabled flag + sessions', async () => {
    const s = useTerminalSessionsStore()
    listMock.mockResolvedValue({ enabled: true, sessions: [sess('a')] })
    await s.ensureForConversation(CONV)
    await s.ensureForConversation(CONV)
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(s.enabled).toBe(true)
    expect(s.sessionsFor(CONV).map((x) => x.id)).toEqual(['a'])
  })

  it('create appends the new session', async () => {
    const s = useTerminalSessionsStore()
    createMock.mockResolvedValue(sess('b', { title: 'Build' }))
    const created = await s.create(CONV, { title: 'Build' })
    expect(created.id).toBe('b')
    expect(s.sessionsFor(CONV).map((x) => x.id)).toEqual(['b'])
  })

  it('kill removes the session and drops its buffer', async () => {
    const s = useTerminalSessionsStore()
    s.applySessionOpened({
      type: 'terminal.session_opened',
      conversation_id: CONV,
      session: sess('a')
    })
    s.applyOutput({ type: 'terminal.output', conversation_id: CONV, session_id: 'a', data: 'hi' })
    expect(s.bufferFor('a')).toBe('hi')
    deleteMock.mockResolvedValue(undefined)
    await s.kill(CONV, 'a')
    expect(s.sessionsFor(CONV)).toEqual([])
    expect(s.bufferFor('a')).toBe('')
  })

  it('folds session_opened / renamed / assigned / closed', () => {
    const s = useTerminalSessionsStore()
    s.applySessionOpened({
      type: 'terminal.session_opened',
      conversation_id: CONV,
      session: sess('a')
    })
    s.applySessionOpened({
      type: 'terminal.session_opened',
      conversation_id: CONV,
      session: sess('b')
    })
    s.applyRenamed({
      type: 'terminal.renamed',
      conversation_id: CONV,
      session_id: 'a',
      title: 'Logs'
    })
    s.applyAssigned({ type: 'terminal.assigned', conversation_id: CONV, session_id: 'b' })
    expect(s.sessionsFor(CONV).find((x) => x.id === 'a')?.title).toBe('Logs')
    expect(s.assignedFor(CONV)?.id).toBe('b')
    s.applyClosed({ type: 'terminal.closed', conversation_id: CONV, session_id: 'a', exit_code: 0 })
    expect(s.sessionsFor(CONV).map((x) => x.id)).toEqual(['b'])
  })

  it('buffers output (capped) and pushes live chunks to subscribers', () => {
    const s = useTerminalSessionsStore()
    const seen: string[] = []
    const unsub = s.subscribe('a', (d) => seen.push(d))
    s.applyOutput({ type: 'terminal.output', conversation_id: CONV, session_id: 'a', data: 'one' })
    s.applyOutput({ type: 'terminal.output', conversation_id: CONV, session_id: 'a', data: 'two' })
    expect(seen).toEqual(['one', 'two'])
    expect(s.bufferFor('a')).toBe('onetwo')
    unsub()
    s.applyOutput({
      type: 'terminal.output',
      conversation_id: CONV,
      session_id: 'a',
      data: 'three'
    })
    expect(seen).toEqual(['one', 'two']) // unsubscribed
    expect(s.bufferFor('a')).toBe('onetwothree') // buffer still accrues
  })

  it('sendInput / sendResize emit control frames over the events WS', () => {
    const s = useTerminalSessionsStore()
    s.sendInput(CONV, 'a', 'ls\r')
    s.sendResize(CONV, 'a', 30, 100)
    expect(sendMock).toHaveBeenCalledWith({
      type: 'terminal.input',
      conversation_id: CONV,
      session_id: 'a',
      data: 'ls\r'
    })
    expect(sendMock).toHaveBeenCalledWith({
      type: 'terminal.resize',
      conversation_id: CONV,
      session_id: 'a',
      rows: 30,
      cols: 100
    })
  })

  it('activeCountFor / assignedFor handle the empty case', () => {
    const s = useTerminalSessionsStore()
    expect(s.activeCountFor(null)).toBe(0)
    expect(s.assignedFor(CONV)).toBeNull()
  })
})
