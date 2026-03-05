/**
 * Settings-related types for the OMNIA frontend.
 */

/** A model entry returned by `GET /config/models`. */
export interface OllamaModel {
  name: string
  size: number
  modified_at: string
  is_active: boolean
  capabilities: {
    vision: boolean
    thinking: boolean
  }
}
