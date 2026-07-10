/** User settings + preferences endpoints (`/api/settings`). */
import { request } from './http'
import type { ToolCatalogResponse } from '../../types/settings'

export const settingsApi = {
  /** Toggle tool confirmations on/off. */
  setToolConfirmations: (enabled: boolean): Promise<{ confirmations_enabled: boolean }> =>
    request<{ confirmations_enabled: boolean }>('/settings/tool-confirmations', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current tool confirmations state from backend. */
  getToolConfirmations: (): Promise<{ confirmations_enabled: boolean }> =>
    request<{ confirmations_enabled: boolean }>('/settings/tool-confirmations'),

  /** Toggle system prompt on/off. */
  setSystemPrompt: (enabled: boolean): Promise<{ system_prompt_enabled: boolean }> =>
    request<{ system_prompt_enabled: boolean }>('/settings/system-prompt', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current system prompt enabled state from backend. */
  getSystemPrompt: (): Promise<{ system_prompt_enabled: boolean }> =>
    request<{ system_prompt_enabled: boolean }>('/settings/system-prompt'),

  /** Toggle tools on/off. */
  setTools: (enabled: boolean): Promise<{ tools_enabled: boolean }> =>
    request<{ tools_enabled: boolean }>('/settings/tools', {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),

  /** Read current tools enabled state from backend. */
  getTools: (): Promise<{ tools_enabled: boolean }> =>
    request<{ tools_enabled: boolean }>('/settings/tools'),

  /** Read the chat tool catalog grouped by plugin (with gating flags). */
  getToolCatalog: (): Promise<ToolCatalogResponse> =>
    request<ToolCatalogResponse>('/settings/tool-catalog'),

  /** Persist the per-chat tool selection (opt-out list of namespaced names). */
  setActiveTools: (disabledTools: string[]): Promise<ToolCatalogResponse> =>
    request<ToolCatalogResponse>('/settings/active-tools', {
      method: 'PUT',
      body: JSON.stringify({ disabled_tools: disabledTools })
    }),

  /** Get all persisted user preferences. */
  getPreferences: (): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>('/settings/preferences'),

  /** Reset all persisted preferences to defaults. */
  resetPreferences: (): Promise<{ deleted: number; message: string }> =>
    request<{ deleted: number; message: string }>('/settings/preferences', { method: 'DELETE' }),
}
