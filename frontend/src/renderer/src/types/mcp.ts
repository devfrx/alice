/** MCP (Model Context Protocol) related types, derived from the generated API contract. */

import type { ApiSchema } from './generated'

export type McpServerTool = ApiSchema<'McpToolOut'>
export type McpServerInfo = ApiSchema<'McpServerOut'>
export type McpServersResponse = ApiSchema<'McpServersResponse'>
export type McpReconnectResponse = ApiSchema<'McpReconnectResponse'>
