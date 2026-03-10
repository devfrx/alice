/** Plugin-related types */

export interface PluginInfo {
  name: string
  version: string
  description: string
  author: string
  enabled: boolean
  tools: PluginTool[]
}

export interface PluginTool {
  name: string
  description: string
}
