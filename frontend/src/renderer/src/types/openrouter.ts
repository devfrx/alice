/** OpenRouter provider types — thin aliases over the generated OpenAPI schemas. */
import type { ApiSchema } from './generated'

export type OpenRouterModel = ApiSchema<'OpenRouterModelOut'>
export type OpenRouterModelsResponse = ApiSchema<'OpenRouterModelsResponse'>
export type OpenRouterCredits = ApiSchema<'OpenRouterCreditsResponse'>

export type LlmProvider = 'lmstudio' | 'ollama' | 'openrouter'
