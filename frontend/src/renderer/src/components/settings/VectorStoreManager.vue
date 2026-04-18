<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Vector Store (Qdrant)</h3>

        <!-- Status bar -->
        <div class="vs-status">
            <div class="vs-status__item">
                <span class="vs-status__dot" :class="stats?.connected ? 'vs-status__dot--ok' : 'vs-status__dot--off'" />
                <span class="vs-status__label">
                    {{ stats?.connected ? 'Connesso' : 'Disconnesso' }}
                </span>
            </div>
            <div v-if="stats" class="vs-status__item">
                <span class="vs-status__label">Modalità: <strong>{{ stats.mode }}</strong></span>
            </div>
        </div>

        <!-- Collections panel -->
        <div v-if="stats?.collections.length" class="vs-collections">
            <div class="vs-collections__header">Collezioni</div>
            <div class="vs-collections__list">
                <div v-for="coll in stats.collections" :key="coll.name" class="vs-coll">
                    <span class="vs-coll__name">{{ coll.name }}</span>
                    <span class="vs-coll__stat">
                        <strong>{{ coll.points_count }}</strong> punti
                    </span>
                    <span class="vs-coll__stat">
                        dim: <strong>{{ coll.vectors_size }}</strong>
                    </span>
                </div>
            </div>
        </div>

        <div v-if="stats && !stats.connected" class="vs-empty">
            Qdrant non disponibile. Verifica la configurazione del backend.
        </div>

        <!-- Tool RAG settings -->
        <div class="vs-section">
            <div class="vs-section__header">Tool RAG</div>

            <div class="vs-row">
                <div class="vs-row__text">
                    <span class="vs-row__label">Abilita Tool RAG</span>
                    <span class="vs-row__hint">Seleziona strumenti rilevanti tramite ricerca vettoriale</span>
                </div>
                <button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.settings.llm.toolRagEnabled }"
                    role="switch" :aria-checked="settingsStore.settings.llm.toolRagEnabled"
                    @click="settingsStore.settings.llm.toolRagEnabled = !settingsStore.settings.llm.toolRagEnabled">
                    <span class="sv__toggle-thumb" />
                </button>
            </div>

            <div class="vs-row">
                <div class="vs-row__text">
                    <span class="vs-row__label">Top-K strumenti</span>
                    <span class="vs-row__hint">Numero massimo di strumenti restituiti dalla ricerca vettoriale</span>
                </div>
                <div class="vs-input-wrap">
                    <input v-model.number="settingsStore.settings.llm.toolRagTopK" type="number" class="vs-input"
                        min="1" max="50" step="1" />
                </div>
            </div>
        </div>

        <!-- Actions -->
        <div class="vs-actions">
            <button class="vs-btn vs-btn--secondary" :disabled="loading" @click="refreshStats">
                Aggiorna statistiche
            </button>
            <button class="vs-btn vs-btn--accent" :disabled="loading || reembedding" @click="onReembed">
                {{ reembedding ? 'Reindicizzazione…' : 'Reindicizza strumenti' }}
            </button>
        </div>

        <!-- Loading / Error -->
        <div v-if="loading" class="vs-loading">Caricamento…</div>
        <div v-if="error" class="vs-error">{{ error }}</div>
    </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../services/api'
import { useSettingsStore } from '../../stores/settings'
import type { VectorStoreStats } from '../../types/settings'

const settingsStore = useSettingsStore()

const stats = ref<VectorStoreStats | null>(null)
const loading = ref(false)
const reembedding = ref(false)
const error = ref<string | null>(null)

async function refreshStats(): Promise<void> {
    loading.value = true
    error.value = null
    try {
        stats.value = await api.getVectorStoreStats()
    } catch (err) {
        error.value = err instanceof Error ? err.message : 'Errore nel caricamento statistiche'
    } finally {
        loading.value = false
    }
}

async function onReembed(): Promise<void> {
    reembedding.value = true
    error.value = null
    try {
        const result = await api.reembedTools()
        if (result.status !== 'ok') {
            error.value = 'Reindicizzazione fallita'
        }
        await refreshStats()
    } catch (err) {
        error.value = err instanceof Error ? err.message : 'Errore nella reindicizzazione'
    } finally {
        reembedding.value = false
    }
}

onMounted(() => {
    refreshStats()
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

/* ── Status bar ────────────────────────────────────────────── */
.vs-status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3, 12px);
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: var(--bg-secondary, #1C1C1C);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-3, 12px);
    align-items: center;
}

.vs-status__item {
    display: flex;
    align-items: center;
    gap: var(--space-1, 4px);
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #A09B90);
}

.vs-status__item strong {
    color: var(--accent, #E8DCC8);
    font-weight: 600;
}

.vs-status__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.vs-status__dot--ok {
    background: var(--success, #5C9A6E);
    box-shadow: 0 0 6px var(--success-glow, rgba(92, 154, 110, 0.4));
}

.vs-status__dot--off {
    background: var(--danger, #B85C5C);
    box-shadow: 0 0 6px var(--danger-glow, rgba(184, 92, 92, 0.4));
}

.vs-status__label {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #A09B90);
}

/* ── Collections ───────────────────────────────────────────── */
.vs-collections {
    margin-bottom: var(--space-3, 12px);
}

.vs-collections__header {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-secondary, #A09B90);
    font-weight: 600;
    margin-bottom: var(--space-2, 8px);
}

.vs-collections__list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2, 8px);
}

.vs-coll {
    display: flex;
    align-items: center;
    gap: var(--space-3, 12px);
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: var(--bg-secondary, #1C1C1C);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    transition: border-color 0.2s;
}

.vs-coll:hover {
    border-color: var(--accent-border, rgba(232, 220, 200, 0.20));
}

.vs-coll__name {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--accent, #E8DCC8);
    font-weight: 500;
    font-family: monospace;
    min-width: 120px;
}

.vs-coll__stat {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #A09B90);
}

.vs-coll__stat strong {
    color: var(--text-primary, #EDEDE9);
    font-weight: 600;
}

/* ── Section ───────────────────────────────────────────────── */
.vs-section {
    margin-bottom: var(--space-3, 12px);
}

.vs-section__header {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-secondary, #A09B90);
    font-weight: 600;
    margin-bottom: var(--space-2, 8px);
}

/* ── Row (toggle / input) ──────────────────────────────────── */
.vs-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2, 8px) 0;
    gap: var(--space-3, 12px);
}

.vs-row__text {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.vs-row__label {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-primary, #EDEDE9);
    font-weight: 500;
}

.vs-row__hint {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-muted, #5F5B53);
}

.vs-input-wrap {
    flex-shrink: 0;
}

.vs-input {
    width: 80px;
    padding: var(--space-1, 4px) var(--space-2, 8px);
    background: var(--bg-input, rgba(237, 227, 213, 0.04));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-primary, #EDEDE9);
    font-size: var(--text-sm, 0.8125rem);
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
}

.vs-input:focus {
    border-color: var(--accent-border, rgba(232, 220, 200, 0.20));
}

/* ── Actions ───────────────────────────────────────────────── */
.vs-actions {
    display: flex;
    gap: var(--space-2, 8px);
    margin-bottom: var(--space-3, 12px);
}

.vs-btn {
    padding: var(--space-1, 4px) var(--space-3, 12px);
    border-radius: var(--radius-sm, 4px);
    font-size: var(--text-sm, 0.8125rem);
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
    transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.vs-btn--secondary {
    background: var(--bg-tertiary, #232323);
    border-color: var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-secondary, #A09B90);
}

.vs-btn--secondary:hover:not(:disabled) {
    background: var(--white-light, rgba(255, 255, 255, 0.06));
    color: var(--text-primary, #EDEDE9);
}

.vs-btn--accent {
    background: var(--accent-dim, rgba(232, 220, 200, 0.10));
    border-color: var(--accent-border, rgba(232, 220, 200, 0.20));
    color: var(--accent, #E8DCC8);
}

.vs-btn--accent:hover:not(:disabled) {
    background: var(--accent-light, rgba(232, 220, 200, 0.08));
    border-color: var(--accent, #E8DCC8);
}

.vs-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

/* ── Empty / Loading / Error ───────────────────────────────── */
.vs-empty {
    color: var(--text-muted, #5F5B53);
    padding: var(--space-4, 16px);
    text-align: center;
    font-size: var(--text-sm, 0.8125rem);
}

.vs-loading {
    color: var(--text-muted, #5F5B53);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
}

.vs-error {
    color: rgba(220, 80, 80, 0.9);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
    background: rgba(220, 80, 80, 0.06);
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-2, 8px);
}

/* ── Reuse SettingsView toggle styles ──────────────────────── */
.sv__toggle {
    position: relative;
    width: 36px;
    height: 20px;
    border-radius: 10px;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    background: var(--surface-3, #2A2A2A);
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
    flex-shrink: 0;
}

.sv__toggle--on {
    background: var(--accent-dim, rgba(232, 220, 200, 0.10));
    border-color: var(--accent-border, rgba(232, 220, 200, 0.20));
}

.sv__toggle-thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-muted, #5F5B53);
    transition: transform 0.2s, background 0.2s;
}

.sv__toggle--on .sv__toggle-thumb {
    transform: translateX(16px);
    background: var(--accent, #E8DCC8);
}
</style>
