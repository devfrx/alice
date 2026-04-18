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
/* ── Shared settings section typography ── */
.settings-section__title {
    margin: 0 0 var(--space-3) 0;
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    letter-spacing: -0.01em;
    color: var(--text-primary);
}

.plugins-hint {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin: 0 0 var(--space-3) 0;
    line-height: var(--leading-snug);
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
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    gap: var(--space-3);
    transition: opacity var(--transition-fast), border-color var(--transition-fast);
}

.plugin-item:hover {
    border-color: var(--border-hover);
}

.plugin-item--disabled {
    opacity: var(--opacity-soft);
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
    font-weight: var(--weight-semibold);
}

.plugin-badge {
    font-size: var(--text-2xs);
    padding: 1px var(--space-1-5);
    border-radius: var(--radius-pill);
    font-weight: var(--weight-medium);
    text-transform: uppercase;
    letter-spacing: var(--tracking-normal);
}

.plugin-badge--active {
    background: var(--success-light);
    color: var(--success);
}

.plugin-badge--inactive {
    background: var(--surface-hover);
    color: var(--text-muted);
}

.plugin-description {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
}

.plugin-footer {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.plugin-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
    opacity: var(--opacity-medium);
}

.plugin-tools-count {
    font-size: var(--text-xs);
    color: var(--accent);
    opacity: var(--opacity-medium);
}

.plugin-tools {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin-top: var(--space-1);
}

.plugin-tool-tag {
    font-size: var(--text-2xs);
    padding: 2px var(--space-1-5);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    cursor: default;
}

/* Toggle switch — aligned with sv__toggle design in SettingsView */
.settings-toggle {
    position: relative;
    width: 36px;
    height: 20px;
    border-radius: var(--radius-pill);
    border: none;
    background: var(--surface-3);
    cursor: pointer;
    transition: background var(--transition-fast);
    flex-shrink: 0;
    padding: 0;
}

.settings-toggle--on {
    background: var(--accent);
}

.settings-toggle__thumb {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 14px;
    height: 14px;
    border-radius: var(--radius-full);
    background: var(--text-primary);
    transition:
        transform var(--transition-fast),
        background var(--transition-fast);
}

.settings-toggle--on .settings-toggle__thumb {
    transform: translateX(16px);
}
</style>
