/** OpenRouter provider endpoints (`/api/openrouter`). */
import { request } from './http'
import type { OpenRouterCredits, OpenRouterModelsResponse } from '../../types/openrouter'

export const openrouterApi = {
  /** List available OpenRouter models (cached backend-side unless force-refreshed). */
  getModels: (forceRefresh = false): Promise<OpenRouterModelsResponse> =>
    request<OpenRouterModelsResponse>(
      `/openrouter/models${forceRefresh ? '?force_refresh=true' : ''}`
    ),

  /** Retrieve the current OpenRouter account credits/usage. */
  getCredits: (): Promise<OpenRouterCredits> => request<OpenRouterCredits>('/openrouter/credits')
}
