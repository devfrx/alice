/**
 * Unit tests for stores/chat.ts — streaming lifecycle + load race guard.
 *
 * Pure Pinia store tests (vitest node env). A fresh Pinia is installed per
 * test. Since the v2 migration (Mossa 2), tool/confirmation/ask_user state
 * lives in the `agentRun` store — the chat store owns only conversations,
 * streaming text/thinking, context, cost and versioning.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useChatStore } from './chat'
import { chatApi } from '../services/api'
import type { ConversationDetail } from '../types/chat'

// finalizeStream() fires loadConversations()/loadConversation() as
// fire-and-forget REST calls; stub the API layer so they resolve instead of
// reaching for a backend (the store swallows their rejections, but resolving
// keeps the test free of stray network noise).
vi.mock('../services/api', () => ({
  chatApi: {
    getConversations: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getConversation: vi.fn().mockResolvedValue({
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: []
    }),
    createConversation: vi.fn().mockResolvedValue({ created_at: '', updated_at: '' })
  },
  resolveBackendUrl: (u: string) => u
}))

beforeEach(() => {
  setActivePinia(createPinia())
})

// ---------------------------------------------------------------------------
// streaming lifecycle
// ---------------------------------------------------------------------------

describe('streaming lifecycle', () => {
  it('finalizeStream() ends the stream and appends the assistant message (in-view)', () => {
    const s = useChatStore()
    const conv: ConversationDetail = {
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: []
    }
    s.currentConversation = conv
    // Drive the store into a streaming state so finalizeStream's guard passes.
    s.addUserMessage('hello')
    expect(s.isStreaming).toBe(true)
    s.appendToStream('hi there')

    s.finalizeStream('c1', 'm1')

    expect(s.isStreaming).toBe(false)
    const last = s.currentConversation!.messages.at(-1)
    expect(last).toMatchObject({ id: 'm1', role: 'assistant', content: 'hi there' })
  })

  it('cancelStream() clears streaming state and preserves partial content', () => {
    const s = useChatStore()
    const conv: ConversationDetail = {
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: []
    }
    s.currentConversation = conv
    s.addUserMessage('hello')
    s.appendToStream('partial')

    s.cancelStream()

    expect(s.isStreaming).toBe(false)
    expect(s.currentStreamContent).toBe('')
    const last = s.currentConversation!.messages.at(-1)
    expect(last).toMatchObject({ role: 'assistant', content: 'partial' })
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
    vi.spyOn(chatApi, 'getConversation').mockImplementation(
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
