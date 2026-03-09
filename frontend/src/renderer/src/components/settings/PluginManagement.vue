<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Plugin</h3>
        <p class="plugins-hint">I plugin aggiungono strumenti (tool) che l'assistente può utilizzare durante le
            conversazioni. Attiva o disattiva i plugin per controllare quali capacità sono disponibili.</p>
        <div v-if="pluginsStore.loading" class="plugins-loading">
            Caricamento plugin...
        </div>
        <div v-else-if="pluginsStore.plugins.length === 0" class="plugins-empty">
            Nessun plugin disponibile
        </div>
        <div v-else class="plugins-list">
            <div v-for="plugin in pluginsStore.plugins" :key="plugin.name" class="plugin-item"
                :class="{ 'plugin-item--disabled': !plugin.enabled }">
                <div class="plugin-info">
                    <div class="plugin-header">
                        <span class="plugin-name">{{ plugin.name }}</span>
                        <span v-if="plugin.enabled" class="plugin-badge plugin-badge--active">Attivo</span>
                        <span v-else class="plugin-badge plugin-badge--inactive">Disattivato</span>
                    </div>
                    <span v-if="plugin.description" class="plugin-description">{{ plugin.description }}</span>
                    <div class="plugin-footer">
                        <span v-if="plugin.version" class="plugin-meta">v{{ plugin.version }}</span>
                        <span v-if="plugin.author" class="plugin-meta">{{ plugin.author }}</span>
                        <span v-if="plugin.tools && plugin.tools.length > 0" class="plugin-tools-count">
                            {{ plugin.tools.length }} strument{{ plugin.tools.length === 1 ? 'o' : 'i' }}
                        </span>
                    </div>
                    <div v-if="plugin.enabled && plugin.tools && plugin.tools.length > 0" class="plugin-tools">
                        <span v-for="tool in plugin.tools" :key="tool.name" class="plugin-tool-tag"
                            :title="tool.description">
                            {{ tool.name }}
                        </span>
                    </div>
                </div>
                <button class="settings-toggle" :class="{ 'settings-toggle--on': plugin.enabled }" role="switch"
                    :aria-checked="plugin.enabled"
                    :aria-label="`${plugin.enabled ? 'Disattiva' : 'Attiva'} plugin ${plugin.name}`"
                    @click="pluginsStore.togglePlugin(plugin.name, !plugin.enabled)">
                    <span class="settings-toggle__thumb" />
                </button>
            </div>
        </div>
    </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { usePluginsStore } from '../../stores/plugins'

const pluginsStore = usePluginsStore()

onMounted(() => {
    pluginsStore.loadPlugins()
})
</script>

<style scoped>
.plugins-hint {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-muted);
    margin: 0 0 var(--space-3, 12px) 0;
    line-height: 1.4;
}

.plugins-loading,
.plugins-empty {
    color: var(--text-muted);
    padding: var(--space-2);
    font-size: var(--text-sm);
}

.plugins-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

.plugin-item {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: var(--space-3);
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
    gap: var(--space-3);
    transition: opacity var(--transition-fast, 0.15s);
}

.plugin-item--disabled {
    opacity: 0.6;
}

.plugin-info {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    flex: 1;
    min-width: 0;
}

.plugin-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.plugin-name {
    font-size: var(--text-sm);
    color: var(--text-primary);
    font-weight: 600;
}

.plugin-badge {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 9999px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.plugin-badge--active {
    background: rgba(46, 204, 113, 0.15);
    color: #2ecc71;
}

.plugin-badge--inactive {
    background: rgba(149, 165, 166, 0.15);
    color: var(--text-muted);
}

.plugin-description {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: 1.3;
}

.plugin-footer {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.plugin-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
    opacity: 0.7;
}

.plugin-tools-count {
    font-size: var(--text-xs);
    color: var(--accent, #c8a23c);
    opacity: 0.8;
}

.plugin-tools {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: var(--space-1, 4px);
}

.plugin-tool-tag {
    font-size: 0.65rem;
    padding: 2px 6px;
    border-radius: var(--radius-sm, 4px);
    background: var(--bg-tertiary, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-secondary);
    cursor: default;
}

/* Toggle switch — mirrors SettingsView toggle styles */
.settings-toggle {
    position: relative;
    width: 40px;
    height: 22px;
    border-radius: 11px;
    border: 1px solid var(--border);
    background: var(--bg-tertiary);
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
    flex-shrink: 0;
    padding: 0;
}

.settings-toggle--on {
    background: rgba(201, 168, 76, 0.2);
    border-color: var(--accent);
    box-shadow: 0 0 8px rgba(201, 168, 76, 0.1);
}

.settings-toggle__thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text-muted);
    transition: transform 0.2s, background 0.2s;
}

.settings-toggle--on .settings-toggle__thumb {
    transform: translateX(18px);
    background: var(--accent);
}
</style>
