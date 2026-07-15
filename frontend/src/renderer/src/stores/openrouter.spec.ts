import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useOpenrouterStore } from './openrouter'
import { useSettingsStore } from './settings'
import type { OpenRouterModel } from '../types/openrouter'

const MODELS: OpenRouterModel[] = [
  {
    id: 'anthropic/claude-sonnet-5',
    name: 'Claude Sonnet 5',
    description: '',
    context_length: 200000,
    pricing: { prompt: 0.000003, completion: 0.000015 },
    supports_tools: true,
    supports_vision: true,
    supports_reasoning: true
  },
  {
    id: 'qwen/qwen3.5-72b',
    name: 'Qwen 3.5 72B',
    description: '',
    context_length: 32768,
    pricing: { prompt: 4e-7, completion: 1.2e-6 },
    supports_tools: true,
    supports_vision: false,
    supports_reasoning: false
  }
]

describe('openrouter store — filtering and favorites', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('filters by search query on id and name', () => {
    const store = useOpenrouterStore()
    store.models = MODELS
    store.searchQuery = 'qwen'
    expect(store.filteredModels.map((m) => m.id)).toEqual(['qwen/qwen3.5-72b'])
  })

  it('filters by capability', () => {
    const store = useOpenrouterStore()
    store.models = MODELS
    store.capabilityFilter = 'vision'
    expect(store.filteredModels.map((m) => m.id)).toEqual(['anthropic/claude-sonnet-5'])
  })

  it('puts favorites first', () => {
    const settings = useSettingsStore()
    settings.settings.llm.openrouterFavorites = ['qwen/qwen3.5-72b']
    const store = useOpenrouterStore()
    store.models = MODELS
    expect(store.filteredModels[0].id).toBe('qwen/qwen3.5-72b')
    expect(store.isFavorite('qwen/qwen3.5-72b')).toBe(true)
  })

  it('toggleFavorite adds and removes', () => {
    const settings = useSettingsStore()
    const store = useOpenrouterStore()
    store.toggleFavorite('a/b')
    expect(settings.settings.llm.openrouterFavorites).toEqual(['a/b'])
    store.toggleFavorite('a/b')
    expect(settings.settings.llm.openrouterFavorites).toEqual([])
  })

  it('selectModel writes the settings model', () => {
    const settings = useSettingsStore()
    const store = useOpenrouterStore()
    store.selectModel('anthropic/claude-sonnet-5')
    expect(settings.settings.llm.openrouterModel).toBe('anthropic/claude-sonnet-5')
  })
})
