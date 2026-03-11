/** MCP (Model Context Protocol) related types. */

export interface McpServerTool {
  name: string
  description: string
}

export interface McpServerInfo {
  name: string
  transport: 'stdio' | 'sse'
  enabled: boolean
  command: string[] | null
  url: string | null
  status: 'connected' | 'disconnected' | 'error' | 'not_loaded'
  tools: McpServerTool[]
}

export interface McpServersResponse {
  servers: McpServerInfo[]
}

export interface McpReconnectResponse {
  status: string
  tools_count: number
}
