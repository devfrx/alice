/** Plugin management + execution endpoints (`/api/plugins`). */
import { request } from './http'
import type { PluginInfo } from '../../types/plugin'

export const pluginsApi = {
  /** List installed plugins. */
  getPlugins: (): Promise<PluginInfo[]> => request<PluginInfo[]>('/plugins'),

  /** Enable or disable a plugin by name. */
  togglePlugin: (name: string, enabled: boolean): Promise<PluginInfo> =>
    request<PluginInfo>(`/plugins/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled })
    }),

  /** Execute a plugin tool directly via REST. */
  executePluginTool: <T = unknown>(
    plugin: string,
    tool: string,
    args: Record<string, unknown> = {}
  ): Promise<{ success: boolean; content: T; error_message?: string }> =>
    request<{ success: boolean; content: T; error_message?: string }>(
      '/plugins/execute',
      {
        method: 'POST',
        body: JSON.stringify({ plugin, tool, args })
      }
    ),
}
