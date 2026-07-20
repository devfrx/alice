<template>
  <section class="settings-section">
    <h3 class="settings-section__title">Server MCP</h3>
    <p class="mcp-hint">
      I server MCP (Model Context Protocol) espongono strumenti esterni che l'assistente può
      utilizzare automaticamente. Configura i server in
      <code>config/default.yaml</code> → <code>mcp.servers</code>.
    </p>

    <!-- Stats bar -->
    <div v-if="mcpStore.servers.length > 0" class="mcp-stats">
      <span class="mcp-stat">
        <strong>{{ mcpStore.servers.length }}</strong> server configurati
      </span>
      <span class="mcp-stat">
        <strong>{{ mcpStore.connectedCount }}</strong> connessi
      </span>
      <span class="mcp-stat">
        <strong>{{ mcpStore.totalTools }}</strong> strumenti disponibili
      </span>
    </div>

    <!-- Loading -->
    <div v-if="mcpStore.loading" class="mcp-loading">Caricamento server MCP...</div>

    <!-- Empty state -->
    <UiEmptyState
      v-else-if="mcpStore.servers.length === 0"
      icon="server"
      title="Nessun server MCP configurato"
      subtitle="Aggiungi server in config/default.yaml per connettere strumenti esterni (filesystem, git, browser, n8n, …)"
    />

    <!-- Server list -->
    <div v-else class="mcp-list">
      <div
        v-for="server in mcpStore.servers"
        :key="server.name"
        class="mcp-server"
        :class="{
          'mcp-server--connected': server.status === 'connected',
          'mcp-server--error': server.status === 'error',
          'mcp-server--disabled': !server.enabled
        }"
      >
        <div class="mcp-server__info">
          <!-- Header row -->
          <div class="mcp-server__header">
            <span class="mcp-server__name">{{ server.name }}</span>
            <span class="mcp-badge" :class="`mcp-badge--${server.status}`">
              {{ statusLabel(server.status) }}
            </span>
            <span class="mcp-badge mcp-badge--transport">
              {{ server.transport.toUpperCase() }}
            </span>
            <span
              class="mcp-badge"
              :class="`mcp-badge--${serverTrustBadge(server).variant}`"
              title="Riflette mcp.servers[].trust_annotations nella config (sola lettura)"
            >
              {{ serverTrustBadge(server).label }}
            </span>
          </div>

          <!-- Connection details -->
          <span class="mcp-server__detail">
            <template v-if="server.transport === 'stdio' && server.command">
              {{ server.command.join(' ') }}
            </template>
            <template v-else-if="server.transport === 'sse' && server.url">
              {{ server.url }}
            </template>
          </span>

          <!-- Footer -->
          <div class="mcp-server__footer">
            <span v-if="server.tools.length > 0" class="mcp-server__tools-count">
              {{ server.tools.length }} strument{{ server.tools.length === 1 ? 'o' : 'i' }}
            </span>
            <span v-else-if="server.status === 'connected'" class="mcp-server__tools-count">
              Nessuno strumento
            </span>
          </div>

          <!-- Tool tags -->
          <div
            v-if="server.status === 'connected' && server.tools.length > 0"
            class="mcp-server__tools"
          >
            <span
              v-for="tool in server.tools"
              :key="tool.name"
              class="mcp-tool-tag"
              :title="toolTitle(tool)"
            >
              <span
                class="mcp-tool-tag__dot"
                :class="`mcp-tool-tag__dot--${toolLevelBadge(tool).variant}`"
              />
              {{ tool.name }}
              <span
                class="mcp-tool-tag__level"
                :class="`mcp-tool-tag__level--${toolLevelBadge(tool).variant}`"
              >
                {{ toolLevelShortLabel(tool) }}
              </span>
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="mcp-server__actions">
          <UiButton
            v-if="server.enabled && server.status !== 'connected'"
            variant="secondary"
            size="sm"
            :disabled="mcpStore.reconnecting === server.name"
            :aria-label="`Riconnetti ${server.name}`"
            :title="`Riconnetti ${server.name}`"
            @click="mcpStore.reconnectServer(server.name)"
          >
            <template #icon>
              <AliceSpinner v-if="mcpStore.reconnecting === server.name" size="xs" variant="dots" />
              <AppIcon v-else name="refresh-cw" :size="14" />
            </template>
            {{ mcpStore.reconnecting === server.name ? 'Connessione...' : 'Riconnetti' }}
          </UiButton>
          <span
            v-else-if="server.status === 'connected'"
            class="mcp-server__connected-dot"
            title="Connesso"
          />
        </div>
      </div>
    </div>

    <!-- Refresh button -->
    <div v-if="mcpStore.servers.length > 0" class="mcp-actions">
      <UiButton
        variant="secondary"
        size="sm"
        :disabled="mcpStore.loading"
        @click="mcpStore.loadServers()"
      >
        Aggiorna stato
      </UiButton>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useMcpStore } from '../../stores/mcp'
import type { McpServerInfo, McpServerTool } from '../../types/mcp'
import { serverTrustBadge, toolLevelBadge } from './mcpToolLevel'
import AppIcon from '../ui/AppIcon.vue'
import UiButton from '../ui/UiButton.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import AliceSpinner from '../ui/AliceSpinner.vue'

const mcpStore = useMcpStore()

function statusLabel(status: McpServerInfo['status']): string {
  switch (status) {
    case 'unknown':
      return 'Sconosciuto'
    case 'connected':
      return 'Connesso'
    case 'disconnected':
      return 'Disconnesso'
    case 'degraded':
      return 'Degradato'
    case 'error':
      return 'Errore'
    case 'not_loaded':
      return 'Non caricato'
  }
}

/**
 * Short in-tag label for the tool level: the full fallback label is too long
 * for a tag, so it is abbreviated here and spelled out in the tooltip.
 */
function toolLevelShortLabel(tool: McpServerTool): string {
  return tool.level === 'fallback' ? 'non annotato' : toolLevelBadge(tool).label
}

/** Tooltip: description + full derived level + gate risk. */
function toolTitle(tool: McpServerTool): string {
  const badge = toolLevelBadge(tool)
  const confirm = tool.requires_confirmation ? 'con conferma' : 'senza conferma'
  return `${tool.description}\nLivello: ${badge.label} — rischio ${tool.risk_level}, ${confirm}`
}

onMounted(() => {
  mcpStore.loadServers()
})
</script>

<style scoped>
/* ── Shared settings section typography ── */
.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.mcp-hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0 0 var(--space-3) 0;
  line-height: var(--leading-snug);
}

.mcp-hint code {
  font-size: var(--text-2xs);
  padding: 1px var(--space-1);
  background: var(--surface-2);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

/* ── Stats bar ──────────────────────────────────────────────── */
.mcp-stats {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}

.mcp-stat {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.mcp-stat strong {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

/* ── Loading / Empty ────────────────────────────────────────── */
.mcp-loading {
  color: var(--text-muted);
  padding: var(--space-2);
  font-size: var(--text-sm);
}

/* ── Server list ────────────────────────────────────────────── */
.mcp-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.mcp-server {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  gap: var(--space-3);
  transition:
    opacity var(--transition-fast),
    border-color var(--transition-fast);
}

.mcp-server:hover {
  border-color: var(--border-hover);
}

.mcp-server--disabled {
  opacity: var(--opacity-soft);
}

.mcp-server__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex: 1;
  min-width: 0;
}

.mcp-server__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.mcp-server__name {
  font-size: var(--text-sm);
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

.mcp-server__detail {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  word-break: break-all;
}

.mcp-server__footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.mcp-server__tools-count {
  font-size: var(--text-xs);
  color: var(--accent);
  opacity: var(--opacity-medium);
}

/* ── Badges ─────────────────────────────────────────────────── */
.mcp-badge {
  font-size: var(--text-2xs);
  padding: 1px var(--space-1-5);
  border-radius: var(--radius-pill);
  font-weight: var(--weight-medium);
  text-transform: uppercase;
  letter-spacing: var(--tracking-normal);
}

.mcp-badge--connected {
  background: var(--success-light);
  color: var(--success);
}

.mcp-badge--disconnected {
  background: var(--surface-hover);
  color: var(--text-muted);
}

.mcp-badge--error {
  background: var(--danger-light);
  color: var(--danger);
}

.mcp-badge--not_loaded {
  background: var(--surface-hover);
  color: var(--text-muted);
}

.mcp-badge--unknown {
  background: var(--surface-hover);
  color: var(--text-muted);
}

.mcp-badge--degraded {
  background: var(--warning-bg);
  color: var(--warning);
}

/* Trust badge variants (serverTrustBadge) */
.mcp-badge--success {
  background: var(--success-light);
  color: var(--success);
}

.mcp-badge--warning {
  background: var(--warning-bg);
  color: var(--warning);
}

.mcp-badge--transport {
  background: var(--surface-2);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
}

/* ── Tool tags ──────────────────────────────────────────────── */
.mcp-server__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.mcp-tool-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-2xs);
  padding: 2px var(--space-1-5);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  cursor: default;
}

.mcp-tool-tag__dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.mcp-tool-tag__dot--success {
  background: var(--success);
}

.mcp-tool-tag__dot--warning {
  background: var(--warning);
}

.mcp-tool-tag__dot--danger {
  background: var(--danger);
}

.mcp-tool-tag__level {
  font-size: var(--text-2xs);
  opacity: var(--opacity-medium);
}

.mcp-tool-tag__level--success {
  color: var(--success);
}

.mcp-tool-tag__level--warning {
  color: var(--warning);
}

.mcp-tool-tag__level--danger {
  color: var(--danger);
}

/* ── Actions & Buttons ──────────────────────────────────────── */
.mcp-server__actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.mcp-server__connected-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--success);
  box-shadow: 0 0 6px var(--success-glow);
}

.mcp-actions {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
}
</style>
