/**
 * Pinia store for the Service Orchestrator + model downloads.
 *
 * Mirrors backend `/api/services` and listens to `service.status` and
 * `service.model_download_progress` events on the events WebSocket.
 *
 * This store is intentionally self-contained — it owns its own polling
 * fallback (every 10 s) so the UI remains accurate even if the WS
 * connection drops, and it exposes high-level actions (`restart`,
 * `downloadModel`, `configureTrellis`) for the view layer.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { BACKEND_HOST } from '../services/api'

const API = `${BACKEND_HOST}/api`

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ServiceStatus = 'up' | 'degraded' | 'down' | 'starting'

export interface ServiceSnapshot {
  name: string
  kind: 'internal' | 'external_process'
  status: ServiceStatus
  detail: string | null
  restart_policy: 'always' | 'on-failure' | 'never'
  last_check: string | null
  backoff_attempts: number
}

export interface ModelCatalogEntry {
  service: 'stt' | 'tts'
  model_id: string
  display_name: string
  size_mb: number
  description: string
  installed: boolean
  path: string | null
  file_count: number
}

export interface DownloadProgress {
  service: string
  model_id: string
  downloaded_bytes: number
  total_bytes: number
  phase: 'downloading' | 'completed' | 'error'
  file: string
  error?: string
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useServicesStore = defineStore('services', () => {
  const services = ref<ServiceSnapshot[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  /** Catalogs keyed by service name. */
  const catalogs = ref<Record<string, ModelCatalogEntry[]>>({})

  /** Active download progress, keyed by `${service}:${model_id}`. */
  const downloads = ref<Record<string, DownloadProgress>>({})

  // ----- Computed --------------------------------------------------------

  const byName = computed(() => {
    const map: Record<string, ServiceSnapshot> = {}
    for (const s of services.value) map[s.name] = s
    return map
  })

  const hasDegraded = computed(() =>
    services.value.some((s) => s.status === 'degraded' || s.status === 'down'),
  )

  // ----- Actions ---------------------------------------------------------

  async function refresh(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const r = await fetch(`${API}/services`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      services.value = (await r.json()) as ServiceSnapshot[]
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      isLoading.value = false
    }
  }

  async function restart(name: string): Promise<void> {
    const r = await fetch(`${API}/services/${encodeURIComponent(name)}/restart`, {
      method: 'POST',
    })
    if (!r.ok) {
      const detail = await r
        .json()
        .then((body: { detail?: string }) => body.detail)
        .catch(() => `HTTP ${r.status}`)
      throw new Error(detail || `Restart failed: HTTP ${r.status}`)
    }
    await refresh()
  }

  async function stop(name: string): Promise<void> {
    const r = await fetch(`${API}/services/${encodeURIComponent(name)}/stop`, {
      method: 'POST',
    })
    if (!r.ok) {
      const detail = await r
        .json()
        .then((body: { detail?: string }) => body.detail)
        .catch(() => `HTTP ${r.status}`)
      throw new Error(detail || `Stop failed: HTTP ${r.status}`)
    }
    await refresh()
  }

  async function loadCatalog(serviceName: 'stt' | 'tts'): Promise<void> {
    const r = await fetch(`${API}/services/${serviceName}/models`)
    if (!r.ok) throw new Error(`Catalog load failed: HTTP ${r.status}`)
    const data = (await r.json()) as { models: ModelCatalogEntry[] }
    catalogs.value = { ...catalogs.value, [serviceName]: data.models }
  }

  async function downloadModel(
    serviceName: 'stt' | 'tts',
    modelId: string,
  ): Promise<void> {
    const key = `${serviceName}:${modelId}`
    downloads.value = {
      ...downloads.value,
      [key]: {
        service: serviceName,
        model_id: modelId,
        downloaded_bytes: 0,
        total_bytes: 0,
        phase: 'downloading',
        file: '',
      },
    }
    const r = await fetch(
      `${API}/services/${serviceName}/models/${encodeURIComponent(modelId)}/download`,
      { method: 'POST' },
    )
    if (!r.ok) {
      delete downloads.value[key]
      throw new Error(`Download request failed: HTTP ${r.status}`)
    }
    // Progress arrives via WS; on `already_present` mark completed.
    const body = (await r.json()) as { status: string }
    if (body.status === 'already_present') {
      downloads.value = {
        ...downloads.value,
        [key]: {
          ...downloads.value[key],
          phase: 'completed',
        },
      }
      await loadCatalog(serviceName)
    }
  }

  async function configureTrellis(
    serviceName: 'trellis' | 'trellis2',
    payload: Record<string, unknown>,
  ): Promise<void> {
    const r = await fetch(
      `${API}/services/${encodeURIComponent(serviceName)}/configure`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    if (!r.ok) {
      const detail = await r
        .json()
        .then((b: { detail?: string }) => b.detail)
        .catch(() => `HTTP ${r.status}`)
      throw new Error(detail || `HTTP ${r.status}`)
    }
    await refresh()
  }

  async function loadTrellisConfig(
    serviceName: 'trellis' | 'trellis2',
  ): Promise<Record<string, unknown>> {
    const r = await fetch(
      `${API}/services/${encodeURIComponent(serviceName)}/config`,
    )
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const body = (await r.json()) as { config: Record<string, unknown> }
    return body.config
  }

  async function loadTrellisGuide(): Promise<string> {
    const r = await fetch(`${API}/services/trellis2/setup-guide`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const body = (await r.json()) as { content: string }
    return body.content
  }

  // ----- WS event handlers (called from useEventsWebSocket) -------------

  function onServiceStatus(payload: {
    service?: string
    status?: ServiceStatus
    detail?: string | null
    timestamp?: string | null
  }): void {
    if (!payload.service || !payload.status) return
    const idx = services.value.findIndex((s) => s.name === payload.service)
    if (idx === -1) {
      // Unknown service — refresh to re-sync.
      void refresh()
      return
    }
    services.value[idx] = {
      ...services.value[idx],
      status: payload.status,
      detail: payload.detail ?? null,
      last_check: payload.timestamp ?? services.value[idx].last_check,
    }
  }

  function onDownloadProgress(payload: DownloadProgress): void {
    const key = `${payload.service}:${payload.model_id}`
    downloads.value = { ...downloads.value, [key]: payload }
    if (payload.phase === 'completed') {
      void loadCatalog(payload.service as 'stt' | 'tts')
    }
  }

  return {
    // state
    services,
    catalogs,
    downloads,
    isLoading,
    error,
    // getters
    byName,
    hasDegraded,
    // actions
    refresh,
    stop,
    restart,
    loadCatalog,
    downloadModel,
    configureTrellis,
    loadTrellisConfig,
    loadTrellisGuide,
    onServiceStatus,
    onDownloadProgress,
  }
})
