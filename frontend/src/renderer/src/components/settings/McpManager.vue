<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Server MCP</h3>
        <p class="mcp-hint">
            I server MCP (Model Context Protocol) espongono strumenti esterni che l'assistente
            può utilizzare automaticamente. Configura i server in
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
        <div v-if="mcpStore.loading" class="mcp-loading">
            Caricamento server MCP...
        </div>

        <!-- Empty state -->
        <div v-else-if="mcpStore.servers.length === 0" class="mcp-empty">
            <div class="mcp-empty__icon">
                <AppIcon name="server" :size="32" :stroke-width="1.5" />
            </div>
            <p class="mcp-empty__text">Nessun server MCP configurato</p>
            <p class="mcp-empty__sub">
                Aggiungi server in <code>config/default.yaml</code> per connettere
                strumenti esterni (filesystem, git, browser, n8n, …)
            </p>
        </div>

        <!-- Server list -->
        <div v-else class="mcp-list">
            <div v-for="server in mcpStore.servers" :key="server.name" class="mcp-server" :class="{
                'mcp-server--connected': server.status === 'connected',
                'mcp-server--error': server.status === 'error',
                'mcp-server--disabled': !server.enabled,
            }">
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
                    <div v-if="server.status === 'connected' && server.tools.length > 0" class="mcp-server__tools">
                        <span v-for="tool in server.tools" :key="tool.name" class="mcp-tool-tag"
                            :title="tool.description">
                            {{ tool.name }}
                        </span>
                    </div>
                </div>

                <!-- Actions -->
                <div class="mcp-server__actions">
                    <button v-if="server.enabled && server.status !== 'connected'" class="mcp-btn mcp-btn--reconnect"
                        :disabled="mcpStore.reconnecting === server.name" :title="`Riconnetti ${server.name}`"
                        @click="mcpStore.reconnectServer(server.name)">
                        <AppIcon name="refresh-cw" :size="14" class="mcp-btn__icon"
                            :class="{ 'mcp-btn__icon--spin': mcpStore.reconnecting === server.name }" />
                        <span v-if="mcpStore.reconnecting !== server.name">Riconnetti</span>
                        <span v-else>Connessione...</span>
                    </button>
                    <span v-else-if="server.status === 'connected'" class="mcp-server__connected-dot"
                        title="Connesso" />
                </div>
            </div>
        </div>

        <!-- Refresh button -->
        <div v-if="mcpStore.servers.length > 0" class="mcp-actions">
            <button class="mcp-btn mcp-btn--refresh" :disabled="mcpStore.loading" @click="mcpStore.loadServers()">
                Aggiorna stato
            </button>
        </div>
    </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useMcpStore } from '../../stores/mcp'
import AppIcon from '../ui/AppIcon.vue'

const mcpStore = useMcpStore()

function statusLabel(status: string): string {
    switch (status) {
        case 'connected': return 'Connesso'
        case 'disconnected': return 'Disconnesso'
        case 'error': return 'Errore'
        case 'not_loaded': return 'Non caricato'
        default: return status
    }
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
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-muted);
    margin: 0 0 var(--space-3, 12px) 0;
    line-height: 1.4;
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
    gap: var(--space-4, 16px);
    margin-bottom: var(--space-3, 12px);
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
    border-radius: var(--radius-sm, 4px);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
}

.mcp-stat {
    font-size: var(--text-xs, 0.75rem);
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

.mcp-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-6) var(--space-4);
    text-align: center;
}

.mcp-empty__icon {
    color: var(--text-muted);
    opacity: var(--opacity-faint);
}

.mcp-empty__text {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    font-weight: var(--weight-medium);
}

.mcp-empty__sub {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-muted);
    line-height: var(--leading-snug);
    max-width: 380px;
}

.mcp-empty__sub code {
    font-size: var(--text-2xs);
    padding: 1px var(--space-1);
    background: var(--surface-2);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-family: var(--font-mono);
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
    transition: opacity var(--transition-fast), border-color var(--transition-fast);
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
    font-size: var(--text-2xs);
    padding: 2px var(--space-1-5);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    cursor: default;
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

.mcp-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-1) var(--space-2-5);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    font-family: var(--font-sans);
    cursor: pointer;
    transition:
        background var(--transition-fast),
        color var(--transition-fast),
        border-color var(--transition-fast);
}

.mcp-btn:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--text-primary);
    border-color: var(--border-hover);
}

.mcp-btn:focus-visible {
    outline: none;
    box-shadow: var(--focus-ring-shadow);
}

.mcp-btn:disabled {
    opacity: var(--opacity-dim);
    cursor: not-allowed;
}

.mcp-btn__icon {
    flex-shrink: 0;
}

.mcp-btn__icon--spin {
    animation: mcp-spin 1s linear infinite;
}

@keyframes mcp-spin {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(360deg);
    }
}

.mcp-actions {
    margin-top: var(--space-3);
    display: flex;
    gap: var(--space-2);
}

.mcp-btn--refresh {
    border-color: var(--border-hover);
}
</style>
