/**
 * Per-domain REST clients for the AL\CE backend (Fase 6).
 *
 * Import the domain namespace you need (`chatApi`, `artifactsApi`, …) or the
 * shared HTTP infrastructure (`ApiError`, `BACKEND_HOST`, `resolveBackendUrl`,
 * `waitForBackend`). There is NO aggregated legacy `api` object.
 */
export { ApiError, BACKEND_HOST, resolveBackendUrl, waitForBackend } from './http'
export { chatApi } from './chat'
export { configApi } from './config'
export { modelsApi } from './models'
export { openrouterApi } from './openrouter'
export { pluginsApi } from './plugins'
export { voiceApi } from './voice'
export { settingsApi } from './settings'
export { calendarApi } from './calendar'
export { auditApi } from './audit'
export { memoryApi, vectorStoreApi } from './memory'
export { mcpApi } from './mcp'
export { mcpMemoryApi } from './mcpMemory'
export { emailApi } from './email'
export { artifactsApi } from './artifacts'
export { tasksApi } from './tasks'
export { scopeApi } from './scope'
export { permissionsApi } from './permissions'
export { terminalApi } from './terminal'
