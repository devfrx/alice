/** MCP server management endpoints (`/api/mcp/servers`). */
import { request } from './http'
import type { McpReconnectResponse, McpServersResponse } from '../../types/mcp'

export const mcpApi = {
  /** List all configured MCP servers with status and tools. */
  getMcpServers: (): Promise<McpServersResponse> => request<McpServersResponse>('/mcp/servers'),

  /** Reconnect a specific MCP server. */
  reconnectMcpServer: (name: string): Promise<McpReconnectResponse> =>
    request<McpReconnectResponse>(`/mcp/servers/${encodeURIComponent(name)}/reconnect`, {
      method: 'POST'
    })
}
