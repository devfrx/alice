/**
 * Settings-related types for the OMNIA frontend.
 * Types aligned with LM Studio v1 REST API model responses.
 */

/** Quantization info for a model. */
export interface ModelQuantization {
  name: string | null
  bits_per_weight: number | null
}

/** A loaded model instance configuration. */
export interface LoadedInstanceConfig {
  context_length: number
  eval_batch_size?: number
  flash_attention?: boolean
  num_experts?: number
  offload_kv_cache_to_gpu?: boolean
}

/** A loaded model instance. */
export interface LoadedInstance {
  id: string
  config: LoadedInstanceConfig
}

/** Model capabilities. */
export interface ModelCapabilities {
  vision: boolean
  thinking: boolean
  trained_for_tool_use: boolean
}

/** A model entry returned by `GET /api/config/models`. */
export interface LMStudioModel {
  name: string
  display_name: string
  type: string
  size: number
  modified_at: string
  is_active: boolean
  loaded: boolean
  capabilities: ModelCapabilities
  architecture: string | null
  quantization: ModelQuantization | null
  params_string: string | null
  format: string | null
  max_context_length: number
  loaded_instances: LoadedInstance[]
}

/** Response from POST /api/models/load. */
export interface ModelLoadResponse {
  type: string
  instance_id: string
  load_time_seconds: number
  status: 'loaded'
  load_config?: Record<string, unknown>
}

/** Response from POST /api/models/unload. */
export interface ModelUnloadResponse {
  instance_id: string
}

/** Download job status values. */
export type DownloadStatus = 'downloading' | 'paused' | 'completed' | 'failed' | 'already_downloaded'

/** Response from POST /api/models/download. */
export interface ModelDownloadResponse {
  job_id?: string
  status: DownloadStatus
  total_size_bytes?: number
  started_at?: string
}

/** Response from GET /api/models/download/{job_id}. */
export interface DownloadStatusResponse {
  job_id: string
  status: DownloadStatus
  bytes_per_second?: number
  estimated_completion?: string
  downloaded_bytes?: number
  total_size_bytes?: number
  started_at?: string
  completed_at?: string
}

/** Response from GET /api/models/status. */
export interface ModelsStatusResponse {
  connected: boolean
  loaded_model_count: number
  total_model_count: number
  loaded_models: string[]
}

/** Model operation status from GET /api/models/operation. */
export type ModelOperationStatus = 'idle' | 'in_progress' | 'completed' | 'failed'

/** Model operation type. */
export type ModelOperationType = 'load' | 'unload' | 'switch'

/** Current model operation response from backend. */
export interface ModelOperationResponse {
  status: ModelOperationStatus
  type?: ModelOperationType
  model?: string
  progress?: number
  error?: string | null
  started_at?: string
}
