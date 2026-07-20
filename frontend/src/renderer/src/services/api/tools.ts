/** Tool-registry catalog endpoint (`/api/tools/catalog`, Fase 2 Agent v2). */
import { request } from './http'
import type { ApiSchema } from '../../types/generated'

export type ToolsCatalogResponse = ApiSchema<'ToolsCatalogResponse'>

export const toolsApi = {
  /**
   * Fetch the flat catalog of every registered tool (name, plugin, label,
   * capabilities, risk level, MCP provenance). Powers the tool picker in the
   * permission-rules manager.
   */
  getCatalog: (): Promise<ToolsCatalogResponse> => request<ToolsCatalogResponse>('/tools/catalog')
}
