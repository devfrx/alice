import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../services/api'
import type { OllamaModel } from '../types/settings'

export interface OmniaSettings {
  llm: {
    model: string
    temperature: number
    maxTokens: number
  }
  stt: {
    language: string
    model: string
  }
  tts: {
    voice: string
    engine: string
  }
  ui: {
    theme: 'dark' | 'light'
    language: string
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<OmniaSettings>({
    llm: {
      model: 'qwen3.5:9b',
      temperature: 0.7,
      maxTokens: 4096
    },
    stt: {
      language: 'it',
      model: 'large-v3'
    },
    tts: {
      voice: 'it_IT-riccardo-x_low',
      engine: 'piper'
    },
    ui: {
      theme: 'dark',
      language: 'it'
    }
  })

  /** All models available on the backend. */
  const models = ref<OllamaModel[]>([])

  /** Whether models are currently being fetched. */
  const isLoadingModels = ref(false)

  /** The model that is currently active (has `is_active === true`). */
  const activeModel = computed(() => models.value.find((m) => m.is_active) ?? null)

  /** Fetch the list of available models from the backend. */
  async function loadModels(): Promise<void> {
    isLoadingModels.value = true
    try {
      models.value = await api.getModels()
    } finally {
      isLoadingModels.value = false
    }
  }

  /** Switch the active LLM model and refresh the model list. */
  async function switchModel(modelName: string): Promise<void> {
    await api.updateConfig({ llm: { model: modelName } })
    await loadModels()
    settings.value.llm.model = modelName
  }

  return { settings, models, isLoadingModels, activeModel, loadModels, switchModel }
})
