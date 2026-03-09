import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { api } from '../services/api'
import type { DownloadStatusResponse, LMStudioModel, ModelOperationResponse } from '../types/settings'

export interface OmniaSettings {
  llm: {
    model: string
    temperature: number
    maxTokens: number
    maxToolIterations: number
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
      model: 'mistralai/ministral-3-14b-reasoning',
      temperature: 0.7,
      maxTokens: 30311,
      maxToolIterations: 25
    },
    stt: {
      language: 'it',
      model: 'large-v3'
    },
    tts: {
      voice: 'models/tts/it_IT-paola-medium',
      engine: 'piper'
    },
    ui: {
      theme: 'dark',
      language: 'it'
    }
  })

  /** Whether tool executions require user confirmation before running. */
  const toolConfirmations = ref<boolean>(true)

  /** Whether the system prompt is sent to the LLM. */
  const systemPromptEnabled = ref<boolean>(true)

  /** Whether tool definitions are sent to the LLM. */
  const toolsEnabled = ref<boolean>(true)

  watch(toolConfirmations, (val) => {
    api.setToolConfirmations(val).catch(console.error)
  })

  watch(systemPromptEnabled, (val) => {
    api.setSystemPrompt(val).catch(console.error)
  })

  watch(toolsEnabled, (val) => {
    api.setTools(val).catch(console.error)
  })

  /** Load toggle states from the backend (persisted preferences). */
  async function loadToggles(): Promise<void> {
    try {
      const [tc, sp, t] = await Promise.all([
        api.getToolConfirmations(),
        api.getSystemPrompt(),
        api.getTools(),
      ])
      toolConfirmations.value = tc.confirmations_enabled
      systemPromptEnabled.value = sp.system_prompt_enabled
      toolsEnabled.value = t.tools_enabled
    } catch (err) {
      console.warn('[settings store] loadToggles failed:', err)
    }
  }

  // Load persisted toggle states from backend on startup
  loadToggles()

  /** Load settings from the backend. */
  async function loadSettings(): Promise<void> {
    try {
      const config = await api.getConfig()
      if (config.llm) {
        const llm = config.llm as Record<string, unknown>
        settings.value.llm.model = (llm.model as string) ?? settings.value.llm.model
        settings.value.llm.temperature = (llm.temperature as number) ?? settings.value.llm.temperature
        settings.value.llm.maxTokens = (llm.max_tokens as number) ?? settings.value.llm.maxTokens
        settings.value.llm.maxToolIterations = (llm.max_tool_iterations as number) ?? settings.value.llm.maxToolIterations
      }
      if (config.stt) {
        const stt = config.stt as Record<string, unknown>
        settings.value.stt.language = (stt.language as string) ?? settings.value.stt.language
        settings.value.stt.model = (stt.model as string) ?? settings.value.stt.model
      }
      if (config.tts) {
        const tts = config.tts as Record<string, unknown>
        settings.value.tts.engine = (tts.engine as string) ?? settings.value.tts.engine
        settings.value.tts.voice = (tts.voice as string) ?? settings.value.tts.voice
      }
      if (config.ui) {
        const ui = config.ui as Record<string, unknown>
        settings.value.ui.theme = (ui.theme as 'dark' | 'light') ?? settings.value.ui.theme
        settings.value.ui.language = (ui.language as string) ?? settings.value.ui.language
      }
    } catch (err) {
      console.warn('[settings store] loadSettings failed:', err)
    }
  }

  /** Save current settings to the backend. */
  async function saveSettings(): Promise<void> {
    try {
      await api.updateConfig({
        llm: {
          temperature: settings.value.llm.temperature,
          max_tokens: settings.value.llm.maxTokens,
          max_tool_iterations: settings.value.llm.maxToolIterations
        },
        stt: {
          language: settings.value.stt.language,
          model: settings.value.stt.model
        },
        tts: {
          engine: settings.value.tts.engine,
          voice: settings.value.tts.voice
        },
        ui: {
          theme: settings.value.ui.theme,
          language: settings.value.ui.language
        }
      })
    } catch (err) {
      console.warn('[settings store] saveSettings failed:', err)
    }
  }

  let saveTimer: ReturnType<typeof setTimeout> | null = null
  watch(settings, () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => saveSettings(), 1000)
  }, { deep: true })

  // Load settings from backend on startup
  loadSettings()

  /** All models available on the backend. */
  const models = ref<LMStudioModel[]>([])

  /** Whether models are currently being fetched. */
  const isLoadingModels = ref(false)

  /** Model keys currently being loaded into LM Studio. */
  const loadingModelKeys = ref<Set<string>>(new Set())

  /** Instance IDs currently being unloaded from LM Studio. */
  const unloadingInstanceIds = ref<Set<string>>(new Set())

  /** LM Studio connection status. */
  const lmStudioConnected = ref(false)

  /** Number of currently loaded models. */
  const loadedModelCount = ref(0)

  /** Active download jobs. */
  const activeDownloads = ref<Map<string, DownloadStatusResponse>>(new Map())

  /** Track active polling timeouts for cleanup. */
  const pollTimeouts = ref<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  /** Current model operation (load/unload/switch) tracked from backend. */
  const currentOperation = ref<ModelOperationResponse | null>(null)

  /** Timer for polling operation status. */
  const operationPollTimer = ref<ReturnType<typeof setTimeout> | null>(null)

  /** Synchronous guard to prevent concurrent resumeOperationTracking calls. */
  let _isResumingOperation = false

  /** The model that is currently active (has `is_active === true`). */
  const activeModel = computed(() => models.value.find((m) => m.is_active) ?? null)

  /** Models that are currently loaded in LM Studio. */
  const loadedModels = computed(() => models.value.filter((m) => m.loaded))

  /** Models that are available but not loaded. */
  const unloadedModels = computed(() => models.value.filter((m) => !m.loaded))

  /** Whether ANY model operation is in progress (global lock). */
  const isAnyOperationInProgress = computed(() =>
    currentOperation.value !== null &&
    currentOperation.value.status === 'in_progress'
  )

  /** Description of the current operation for UI display. */
  const operationDescription = computed(() => {
    const op = currentOperation.value
    if (!op || op.status === 'idle') return null
    const typeLabel = op.type === 'load' ? 'Caricamento' : op.type === 'unload' ? 'Rimozione dalla memoria' : 'Cambio modello'
    return `${typeLabel}: ${op.model ?? '...'}`
  })

  /** Whether any model is currently being loaded. */
  const isLoadingModel = computed(() => loadingModelKeys.value.size > 0)

  /** Whether any model is currently being unloaded. */
  const isUnloadingModel = computed(() => unloadingInstanceIds.value.size > 0)

  /** Check if a specific model is currently being loaded. */
  function isModelLoading(key: string): boolean {
    return loadingModelKeys.value.has(key)
  }

  /** Check if a specific instance is currently being unloaded. */
  function isInstanceUnloading(instanceId: string): boolean {
    return unloadingInstanceIds.value.has(instanceId)
  }

  /** Check LM Studio connection and update status. */
  async function checkConnection(): Promise<void> {
    try {
      const status = await api.getModelsStatus()
      lmStudioConnected.value = status.connected
      loadedModelCount.value = status.loaded_model_count
    } catch {
      lmStudioConnected.value = false
      loadedModelCount.value = 0
    }
  }

  /** Sync config model with the model currently loaded in LM Studio. */
  async function syncModel(): Promise<void> {
    try {
      const result = await api.syncModel()
      if (result.synced && result.model) {
        settings.value.llm.model = result.model
        await loadModels()
      }
    } catch {
      // Backend unreachable — ignore silently
    }
  }

  /** Fetch the list of available models from the backend. */
  async function loadModels(): Promise<void> {
    if (models.value.length === 0) {
      isLoadingModels.value = true
    }
    try {
      models.value = await api.getModels()
      await checkConnection()
    } finally {
      isLoadingModels.value = false
    }
  }

  /** Check backend for active operation and resume polling if needed. */
  async function resumeOperationTracking(): Promise<void> {
    if (operationPollTimer.value !== null || _isResumingOperation) return
    _isResumingOperation = true
    try {
      const op = await api.getModelOperation()
      if (op.status === 'in_progress') {
        currentOperation.value = op
        if (op.model && op.type !== 'unload') {
          loadingModelKeys.value = new Set([...loadingModelKeys.value, op.model])
        }
        if (op.model && op.type === 'unload') {
          unloadingInstanceIds.value = new Set([...unloadingInstanceIds.value, op.model])
        }
        startOperationPolling()
      }
    } catch {
      // Backend unreachable
    } finally {
      _isResumingOperation = false
    }
  }

  /** Start polling the backend for operation status. */
  function startOperationPolling(): void {
    stopOperationPolling()
    const clientType = currentOperation.value?.type ?? null
    const poll = async (): Promise<void> => {
      try {
        const op = await api.getModelOperation()
        // Preserve client-side 'switch' type — backend only knows 'load'
        if (clientType === 'switch' && op.type === 'load') {
          op.type = 'switch'
        }
        currentOperation.value = op
        if (op.status === 'in_progress') {
          operationPollTimer.value = setTimeout(poll, 500)
        } else {
          // Operation finished — refresh models and clear after a delay
          if (op.status === 'completed') await loadModels()
          operationPollTimer.value = setTimeout(() => {
            currentOperation.value = null
            stopOperationPolling()
          }, 2000)
        }
      } catch {
        currentOperation.value = null
        stopOperationPolling()
      }
    }
    poll()
  }

  /** Stop operation status polling. */
  function stopOperationPolling(): void {
    if (operationPollTimer.value !== null) {
      clearTimeout(operationPollTimer.value)
      operationPollTimer.value = null
    }
  }

  /** Load a model into LM Studio. */
  async function loadModel(
    modelKey: string,
    config?: { context_length?: number; flash_attention?: boolean }
  ): Promise<void> {
    if (isAnyOperationInProgress.value) throw new Error('Un\'altra operazione è in corso')
    loadingModelKeys.value = new Set([...loadingModelKeys.value, modelKey])
    currentOperation.value = { status: 'in_progress', type: 'load', model: modelKey }
    startOperationPolling()
    try {
      await api.loadModel(modelKey, config)
      await loadModels()
      // If the loaded model is not active, switch to it so selectors stay in sync
      const justLoaded = models.value.find((m) => m.name === modelKey)
      if (justLoaded && !justLoaded.is_active) {
        try {
          await api.updateConfig({ llm: { model: modelKey } })
          settings.value.llm.model = modelKey
        } catch {
          // 409 is expected if backend is still busy — model is loaded regardless
        }
      }
    } catch (err) {
      currentOperation.value = null
      stopOperationPolling()
      throw err
    } finally {
      const next = new Set(loadingModelKeys.value)
      next.delete(modelKey)
      loadingModelKeys.value = next
    }
  }

  /** Unload a model instance from LM Studio. */
  async function unloadModel(instanceId: string): Promise<void> {
    if (isAnyOperationInProgress.value) throw new Error('Un\'altra operazione è in corso')
    unloadingInstanceIds.value = new Set([...unloadingInstanceIds.value, instanceId])
    currentOperation.value = { status: 'in_progress', type: 'unload', model: instanceId }
    startOperationPolling()
    try {
      await api.unloadModel(instanceId)
      await loadModels()
    } catch (err) {
      currentOperation.value = null
      stopOperationPolling()
      throw err
    } finally {
      const next = new Set(unloadingInstanceIds.value)
      next.delete(instanceId)
      unloadingInstanceIds.value = next
    }
  }

  /** Start downloading a model and begin polling for status. */
  async function downloadModel(model: string, quantization?: string): Promise<void> {
    const response = await api.downloadModel(model, quantization)
    if (response.job_id && response.status === 'downloading') {
      pollDownloadStatus(response.job_id)
    } else if (response.status === 'already_downloaded') {
      await loadModels()
    }
  }

  /** Poll download status every 2s until completed or failed. */
  function pollDownloadStatus(jobId: string): void {
    const poll = async (): Promise<void> => {
      try {
        const status = await api.getDownloadStatus(jobId)
        activeDownloads.value = new Map(activeDownloads.value.set(jobId, status))
        if (status.status === 'downloading' || status.status === 'paused') {
          const tid = setTimeout(poll, 2000)
          pollTimeouts.value.set(jobId, tid)
        } else {
          pollTimeouts.value.delete(jobId)
          if (status.status === 'completed') {
            await loadModels()
          }
          const cleanupTid = setTimeout(() => {
            const updated = new Map(activeDownloads.value)
            updated.delete(jobId)
            activeDownloads.value = updated
          }, 5000)
          pollTimeouts.value.set(`cleanup-${jobId}`, cleanupTid)
        }
      } catch {
        pollTimeouts.value.delete(jobId)
        const updated = new Map(activeDownloads.value)
        updated.delete(jobId)
        activeDownloads.value = updated
      }
    }
    poll()
  }

  /** Cancel all active polling timers. */
  function stopAllPolling(): void {
    for (const tid of pollTimeouts.value.values()) {
      clearTimeout(tid)
    }
    pollTimeouts.value.clear()
    stopOperationPolling()
  }

  /** Switch the active LLM model. The backend loads it automatically. */
  async function switchModel(modelName: string): Promise<void> {
    if (isAnyOperationInProgress.value) throw new Error('Un\'altra operazione è in corso')
    loadingModelKeys.value = new Set([...loadingModelKeys.value, modelName])
    currentOperation.value = { status: 'in_progress', type: 'switch', model: modelName }
    startOperationPolling()
    try {
      await api.updateConfig({ llm: { model: modelName } })
      await loadModels()
      settings.value.llm.model = modelName
    } catch (err) {
      currentOperation.value = null
      stopOperationPolling()
      throw err
    } finally {
      const next = new Set(loadingModelKeys.value)
      next.delete(modelName)
      loadingModelKeys.value = next
    }
  }

  return {
    settings,
    toolConfirmations,
    systemPromptEnabled,
    toolsEnabled,
    models,
    isLoadingModels,
    isLoadingModel,
    isUnloadingModel,
    loadingModelKeys,
    unloadingInstanceIds,
    lmStudioConnected,
    loadedModelCount,
    activeDownloads,
    activeModel,
    loadedModels,
    unloadedModels,
    isModelLoading,
    isInstanceUnloading,
    checkConnection,
    syncModel,
    loadModels,
    loadModel,
    unloadModel,
    downloadModel,
    switchModel,
    stopAllPolling,
    currentOperation,
    isAnyOperationInProgress,
    operationDescription,
    startOperationPolling,
    stopOperationPolling,
    resumeOperationTracking,
    loadSettings,
    saveSettings,
    loadToggles
  }
})
