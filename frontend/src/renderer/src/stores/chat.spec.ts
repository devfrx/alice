/**
 * Unit tests for stores/chat.ts — `pendingAskUser` lifecycle (Fase 4 FE).
 *
 * Pure Pinia store tests (vitest node env). A fresh Pinia is installed per
 * test. Focused on the inline `ask_user` prompt state: the add/remove mutators
 * plus the invariant that NO ask_user prompt lingers after a stream ends
 * (cancel / finalize) or after its tool execution completes — a lingering
 * prompt after stream end is a bug.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useChatStore } from './chat'
import { api } from '../services/api'
import type { AskUserRequest, ConversationDetail } from '../types/chat'

// finalizeStream() fires loadConversations()/loadConversation() as
// fire-and-forget REST calls; stub the API layer so they resolve instead of
// reaching for a backend (the store swallows their rejections, but resolving
// keeps the test free of stray network noise).
vi.mock('../services/api', () => ({
  api: {
    getConversations: vi.fn().mockResolvedValue([]),
    getConversation: vi.fn().mockResolvedValue({
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: [],
    }),
    createConversation: vi.fn().mockResolvedValue({ created_at: '', updated_at: '' }),
  },
  resolveBackendUrl: (u: string) => u,
}))

function askReq(executionId: string, question = 'Which file?', options?: string[]): AskUserRequest {
  return { executionId, question, options }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

// ---------------------------------------------------------------------------
// add / remove mutators
// ---------------------------------------------------------------------------

describe('pendingAskUser add/remove', () => {
  it('addPendingAskUser exposes the request keyed by executionId', () => {
    const s = useChatStore()
    expect(s.pendingAskUser).toEqual({})

    s.addPendingAskUser(askReq('e1', 'Pick one', ['a', 'b']))

    expect(Object.keys(s.pendingAskUser)).toEqual(['e1'])
    expect(s.pendingAskUser['e1']).toMatchObject({
      executionId: 'e1',
      question: 'Pick one',
      options: ['a', 'b'],
    })
  })

  it('removePendingAskUser clears only the matching entry', () => {
    const s = useChatStore()
    s.addPendingAskUser(askReq('e1'))
    s.addPendingAskUser(askReq('e2'))

    s.removePendingAskUser('e1')

    expect(s.pendingAskUser['e1']).toBeUndefined()
    expect(s.pendingAskUser['e2']).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// cleanup on stream end / tool completion
// ---------------------------------------------------------------------------

describe('pendingAskUser cleanup', () => {
  it('cancelStream() clears all pending ask_user prompts', () => {
    const s = useChatStore()
    s.addPendingAskUser(askReq('e1'))
    s.addPendingAskUser(askReq('e2'))

    s.cancelStream()

    expect(s.pendingAskUser).toEqual({})
  })

  it('finalizeStream() clears pending ask_user prompts (in-view branch)', () => {
    const s = useChatStore()
    const conv: ConversationDetail = {
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: [],
    }
    s.currentConversation = conv
    // Drive the store into a streaming state so finalizeStream's guard passes.
    s.addUserMessage('hello')
    expect(s.isStreaming).toBe(true)

    s.addPendingAskUser(askReq('e1'))
    s.finalizeStream('c1', 'm1')

    expect(s.isStreaming).toBe(false)
    expect(s.pendingAskUser).toEqual({})
  })

  it('completeToolExecution() drops the ask_user prompt for that execution', () => {
    const s = useChatStore()
    s.addToolExecution('e1', 'ask_user')
    s.addPendingAskUser(askReq('e1'))

    s.completeToolExecution('e1', 'answered', true)

    expect(s.pendingAskUser['e1']).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// loadConversation race (latest selection wins)
// ---------------------------------------------------------------------------

describe('loadConversation race guard', () => {
  it('discards a stale loadConversation result (latest selection wins)', async () => {
    const store = useChatStore()
    // Do NOT pre-seed `conversations` with A/B (or seed with message_count > 0) so the
    // API path is taken rather than the local-empty short-circuit.
    const resolvers: Record<string, (v: unknown) => void> = {}
    vi.spyOn(api, 'getConversation').mockImplementation(
      (id: string) =>
        new Promise((res) => {
          resolvers[id] = res
        }) as never
    )

    const pA = store.loadConversation('A')
    const pB = store.loadConversation('B')
    // B resolves first, then the stale A resolves later.
    resolvers['B']({ id: 'B', title: 'B', created_at: '', updated_at: '', messages: [] })
    await pB
    resolvers['A']({ id: 'A', title: 'A', created_at: '', updated_at: '', messages: [] })
    await pA

    expect(store.currentConversation?.id).toBe('B')
  })
})
