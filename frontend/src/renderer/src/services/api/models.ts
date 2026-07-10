/** LLM model management endpoints (`/api/models`, `/api/config/models`). */
import { request } from './http'
import type {
  DownloadStatusResponse,
  LMStudioModel,
  ModelDownloadResponse,
  ModelLoadResponse,
  ModelOperationResponse,
  ModelUnloadResponse,
  ModelsStatusResponse,
} from '../../types/settings'

export const modelsApi = {
  /** Retrieve the list of available LLM models (via /config/models). */
  getModels: (): Promise<LMStudioModel[]> =>
    request<LMStudioModel[]>('/config/models'),

  /** Retrieve the list of available LLM models (via /models). */
  listModels: (): Promise<LMStudioModel[]> =>
    request<LMStudioModel[]>('/models'),

  /** Load a model into LM Studio. */
  loadModel: (
    model: string,
    config?: { context_length?: number; flash_attention?: boolean }
  ): Promise<ModelLoadResponse> =>
    request<ModelLoadResponse>('/models/load', {
      method: 'POST',
      body: JSON.stringify({ model, ...config })
    }),

  /** Unload a model instance from LM Studio. */
  unloadModel: (instanceId: string): Promise<ModelUnloadResponse> =>
    request<ModelUnloadResponse>('/models/unload', {
      method: 'POST',
      body: JSON.stringify({ instance_id: instanceId })
    }),

  /** Start downloading a model. */
  downloadModel: (model: string, quantization?: string): Promise<ModelDownloadResponse> =>
    request<ModelDownloadResponse>('/models/download', {
      method: 'POST',
      body: JSON.stringify({ model, ...(quantization ? { quantization } : {}) })
    }),

  /** Get download job status. */
  getDownloadStatus: (jobId: string): Promise<DownloadStatusResponse> =>
    request<DownloadStatusResponse>(`/models/download/${encodeURIComponent(jobId)}`),

  /** Get quick LM Studio connection status + model summary. */
  getModelsStatus: (): Promise<ModelsStatusResponse> =>
    request<ModelsStatusResponse>('/models/status'),

  /** Get current model operation status. */
  getModelOperation: (): Promise<ModelOperationResponse> =>
    request<ModelOperationResponse>('/models/operation'),
}
