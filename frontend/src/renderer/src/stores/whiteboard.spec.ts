import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useWhiteboardStore } from './whiteboard'
import { api } from '../services/api'

describe('whiteboard store scoping', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('reset() clears boards/total/currentBoard', () => {
    const store = useWhiteboardStore()
    store.boards = [{ board_id: 'x' }] as never
    store.total = 1
    store.reset()
    expect(store.boards).toEqual([])
    expect(store.total).toBe(0)
    expect(store.currentBoard).toBeNull()
  })

  it('loadBoards forwards the conversation_id', async () => {
    const store = useWhiteboardStore()
    const spy = vi
      .spyOn(api, 'getWhiteboards')
      .mockResolvedValue({ items: [], total: 0 } as never)
    await store.loadBoards('conv-9')
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: 'conv-9' }))
  })
})
