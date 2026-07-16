import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { openrouterApi } from '../services/api'
import type { OpenRouterCredits, OpenRouterModel } from '../types/openrouter'
import { useSettingsStore } from './settings'

export type CapabilityFilter = 'all' | 'tools' | 'vision' | 'reasoning'

export const useOpenrouterStore = defineStore('openrouter', () => {
  const settingsStore = useSettingsStore()

  const models = ref<OpenRouterModel[]>([])
  const credits = ref<OpenRouterCredits | null>(null)
  const loadingCatalog = ref(false)
  const loadingCredits = ref(false)
  const error = ref<string | null>(null)

  const searchQuery = ref('')
  const capabilityFilter = ref<CapabilityFilter>('all')

  const favorites = computed(() => settingsStore.settings.llm.openrouterFavorites)

  /** Whether the given model id is in the user's favorites. */
  function isFavorite(id: string): boolean {
    return favorites.value.includes(id)
  }

  const filteredModels = computed<OpenRouterModel[]>(() => {
    const q = searchQuery.value.trim().toLowerCase()
    let list = models.value
    if (q) {
      list = list.filter((m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
    }
    if (capabilityFilter.value !== 'all') {
      const key = `supports_${capabilityFilter.value}` as
        | 'supports_tools'
        | 'supports_vision'
        | 'supports_reasoning'
      list = list.filter((m) => m[key])
    }
    // Favorites first, catalog order preserved otherwise (stable sort).
    return [...list].sort((a, b) => Number(isFavorite(b.id)) - Number(isFavorite(a.id)))
  })

  /** Fetch the OpenRouter model catalog (cached backend-side unless forced). */
  async function loadCatalog(force = false): Promise<void> {
    loadingCatalog.value = true
    error.value = null
    try {
      const resp = await openrouterApi.getModels(force)
      models.value = resp.models
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loadingCatalog.value = false
    }
  }

  /** Fetch the current OpenRouter account credits/usage. */
  async function loadCredits(): Promise<void> {
    loadingCredits.value = true
    try {
      credits.value = await openrouterApi.getCredits()
    } catch {
      credits.value = null
    } finally {
      loadingCredits.value = false
    }
  }

  /** Add or remove a model id from favorites. */
  function toggleFavorite(id: string): void {
    const favs = settingsStore.settings.llm.openrouterFavorites
    const idx = favs.indexOf(id)
    if (idx >= 0) favs.splice(idx, 1)
    else favs.push(id)
    // Persistence: the settings store's autosave (deep watch) does the PUT.
  }

  /** Select a model as the active OpenRouter model. */
  function selectModel(id: string): void {
    settingsStore.settings.llm.openrouterModel = id
  }

  return {
    models,
    credits,
    loadingCatalog,
    loadingCredits,
    error,
    searchQuery,
    capabilityFilter,
    favorites,
    filteredModels,
    isFavorite,
    loadCatalog,
    loadCredits,
    toggleFavorite,
    selectModel
  }
})
