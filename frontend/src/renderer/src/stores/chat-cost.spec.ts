/**
 * Unit tests for stores/chat.ts — conversation cost accounting (Task 15).
 *
 * `conversationCost` starts from the persisted `total_cost` (set via
 * `setConversationCost`) and accumulates live per-turn costs reported on
 * `turn.finished` (`addTurnCost`). Costs are OpenRouter-only: local
 * providers report `null`/`undefined`, which must be a no-op.
 */
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from './chat'

describe('conversation cost accounting', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('accumulates live turn costs on top of the persisted total', () => {
    const store = useChatStore()
    store.setConversationCost(0.01)
    store.addTurnCost(0.002)
    store.addTurnCost(null) // turno senza costo → no-op
    expect(store.conversationCost).toBeCloseTo(0.012)
  })

  it('starts from null and ignores null totals', () => {
    const store = useChatStore()
    expect(store.conversationCost).toBeNull()
    store.addTurnCost(0.005)
    expect(store.conversationCost).toBeCloseTo(0.005)
  })
})
