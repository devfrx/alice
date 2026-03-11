/**
 * Pinia store for MCP server management.
 *
 * Provides reactive state for listing, inspecting, and reconnecting
 * MCP servers configured in the backend.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../services/api'
import type { McpServerInfo } from '../types/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServerInfo[]>([])
  const loading = ref(false)
  const reconnecting = ref<string | null>(null)

  const connectedCount = computed(
    () => servers.value.filter((s) => s.status === 'connected').length,
  )

  const totalTools = computed(
    () => servers.value.reduce((sum, s) => sum + s.tools.length, 0),
  )

  async function loadServers(): Promise<void> {
    loading.value = true
    try {
      const res = await api.getMcpServers()
      servers.value = res.servers
    } catch (err) {
      console.error('[mcp store] loadServers failed:', err)
    } finally {
      loading.value = false
    }
  }

  async function reconnectServer(name: string): Promise<void> {
    reconnecting.value = name
    try {
      await api.reconnectMcpServer(name)
      await loadServers()
    } catch (err) {
      console.error(`[mcp store] reconnect '${name}' failed:`, err)
      await loadServers()
    } finally {
      reconnecting.value = null
    }
  }

  return {
    servers,
    loading,
    reconnecting,
    connectedCount,
    totalTools,
    loadServers,
    reconnectServer,
  }
})
