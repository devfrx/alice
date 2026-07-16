/** Server configuration endpoints (`/api/config`). */
import { request } from './http'

export const configApi = {
  /** Retrieve the current server configuration. */
  getConfig: (): Promise<Record<string, unknown>> => request<Record<string, unknown>>('/config'),

  /** Update the server configuration. */
  updateConfig: (config: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/config', {
      method: 'PUT',
      body: JSON.stringify(config)
    }),

  /**
   * Retrieve the full merged-and-validated configuration (secrets redacted).
   *
   * Unlike {@link getConfig} (a curated subset), this returns the entire
   * resolved config tree — used to read sections the curated `/config`
   * endpoint does not expose, e.g. `agent.prompts`.
   */
  getResolvedConfig: (): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/config/resolved'),

  /**
   * Set a single dotted-path config value in a layer, validate and persist.
   *
   * Mirrors the backend layered-config `PATCH /config` endpoint. Used for
   * config keys outside the curated PUT `/config` body (e.g.
   * `agent.prompts.persona`, `agent.prompts.tier_guidance`).
   *
   * @param path  - Dotted path, e.g. `"agent.prompts.persona"`.
   * @param value - Any JSON-serialisable value.
   * @param layer - Target layer (`preferences` default, matching the backend default).
   * @returns The full resolved config after the change.
   */
  patchConfig: (
    path: string,
    value: unknown,
    layer: 'preferences' | 'user' | 'system' | 'runtime' = 'preferences'
  ): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/config', {
      method: 'PATCH',
      body: JSON.stringify({ path, value, layer })
    }),

  /** Sync config with the model currently loaded in LM Studio. */
  syncModel: (): Promise<{ synced: boolean; model?: string; reason?: string }> =>
    request<{ synced: boolean; model?: string; reason?: string }>('/config/sync-model', {
      method: 'POST'
    })
}
