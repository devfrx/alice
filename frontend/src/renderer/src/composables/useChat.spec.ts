/**
 * Unit tests for composables/useChat.ts — post-turn context frame gating
 * (review T11 regression pin).
 *
 * The backend emits the REAL `context.usage` (is_estimated=false) and the
 * post-stream `context.compaction` frames AFTER the engine's `turn.finished`.
 * By then `finalizeStream` has nulled `streamingConversationId`, so the
 * handlers must gate on the sticky `lastStreamedConversationId` instead —
 * otherwise the post-turn tail is always dropped and the context bar never
 * receives real token counts.
 *
 * The composable is mounted inside an `effectScope` with the ws/api services
 * mocked; frames are injected through the dispatcher that `useChat` registers
 * via `wsManager.onFrame`.
 */
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

import { useChat } from './useChat'
import { wsManager } from '../services/ws'
import { useChatStore } from '../stores/chat'
import type { ConversationDetail } from '../types/chat'
import type { ChatServerMessage } from '../types/generated'

vi.mock('../services/ws', () => ({
  wsManager: {
    onFrame: vi.fn(),
    offFrame: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    send: vi.fn(),
    disconnect: vi.fn(),
    isConnected: false
  }
}))

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
    createConversation: vi.fn().mockResolvedValue({ created_at: '', updated_at: '' }),
    uploadFile: vi.fn()
  },
  resolveBackendUrl: (u: string) => u
}))

vi.mock('../stores/settings', () => ({
  useSettingsStore: () => ({
    toolConfirmations: true,
    syncModel: vi.fn().mockResolvedValue(undefined)
  })
}))

function conversation(id: string): ConversationDetail {
  return { id, title: null, created_at: '', updated_at: '', messages: [] }
}

function contextUsage(overrides: Partial<ChatServerMessage> = {}): ChatServerMessage {
  return {
    type: 'context.usage',
    used: 1200,
    available: 800,
    context_window: 2000,
    percentage: 0.6,
    was_compressed: false,
    messages_summarized: 0,
    is_estimated: false,
    ...overrides
  } as ChatServerMessage
}

let scope: EffectScope
let dispatch: (frame: ChatServerMessage) => void

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  scope = effectScope()
  scope.run(() => useChat())
  // The frame dispatcher useChat registered on the (mocked) ws manager.
  dispatch = (wsManager.onFrame as Mock).mock.calls[0][0]
})

describe('post-turn context frame gating (review T11)', () => {
  it('applies a context.usage frame arriving AFTER finalizeStream (post-turn tail)', () => {
    const store = useChatStore()
    store.currentConversation = conversation('c1')
    store.addUserMessage('hello')
    // turn.finished → finalizeStream nulls streamingConversationId.
    store.finalizeStream('c1', 'm1')
    expect(store.streamingConversationId).toBeNull()

    // The REAL post-turn usage frame must still land on the context bar.
    dispatch(contextUsage())

    expect(store.contextInfo).not.toBeNull()
    expect(store.contextInfo).toMatchObject({
      used: 1200,
      available: 800,
      contextWindow: 2000,
      percentage: 0.6,
      isEstimated: false
    })
  })

  it('applies a post-turn context.compaction frame (started → compressing flag)', () => {
    const store = useChatStore()
    store.currentConversation = conversation('c1')
    store.addUserMessage('hello')
    store.finalizeStream('c1', 'm1')
    expect(store.isCompressingContext).toBe(false)

    dispatch({ type: 'context.compaction', phase: 'started' } as ChatServerMessage)

    expect(store.isCompressingContext).toBe(true)
  })

  it('drops context frames when the user is viewing a DIFFERENT conversation', () => {
    const store = useChatStore()
    store.currentConversation = conversation('c1')
    store.addUserMessage('hello')
    store.finalizeStream('c1', 'm1')

    // The user navigated away: the frame belongs to c1's turn, not c2's view.
    store.currentConversation = conversation('c2')
    dispatch(contextUsage())

    expect(store.contextInfo).toBeNull()
  })
})
