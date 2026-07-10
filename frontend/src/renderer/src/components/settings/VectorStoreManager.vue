<template>
  <section class="settings-section">
    <h3 class="settings-section__title">Vector Store (Qdrant)</h3>

    <!-- Status bar -->
    <div class="vs-status">
      <div class="vs-status__item">
        <span
          class="vs-status__dot"
          :class="stats?.connected ? 'vs-status__dot--ok' : 'vs-status__dot--off'"
        />
        <span class="vs-status__label">
          {{ stats?.connected ? 'Connesso' : 'Disconnesso' }}
        </span>
      </div>
      <div v-if="stats" class="vs-status__item">
        <span class="vs-status__label"
          >Modalità: <strong>{{ stats.mode }}</strong></span
        >
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

    <!-- RAG readiness feedback -->
    <div v-if="rag && !rag.ready" class="vs-rag-warn">
      <strong>RAG non disponibile.</strong>
      Memory e Tool RAG sono disattivati: {{ rag.reason }}. Premi <em>Ripara / Reset</em> per
      ricreare il vector store.
    </div>

    <!-- Tool RAG settings -->
    <div class="vs-section">
      <div class="vs-section__header">Tool RAG</div>

      <div class="vs-row">
        <div class="vs-row__text">
          <span class="vs-row__label">Abilita Tool RAG</span>
          <span class="vs-row__hint">Seleziona strumenti rilevanti tramite ricerca vettoriale</span>
        </div>
        <UiToggle v-model="settingsStore.settings.llm.toolRagEnabled" aria-label="Tool RAG" />
      </div>

      <div class="vs-row">
        <div class="vs-row__text">
          <span class="vs-row__label">Top-K strumenti</span>
          <span class="vs-row__hint"
            >Numero massimo di strumenti restituiti dalla ricerca vettoriale</span
          >
        </div>
        <div class="vs-input-wrap">
          <input
            v-model.number="settingsStore.settings.llm.toolRagTopK"
            type="number"
            class="vs-input"
            min="1"
            max="50"
            step="1"
          />
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
      <button
        class="vs-btn vs-btn--danger"
        :disabled="loading || repairing"
        title="Cancella e ricrea il vector store embedded (operazione manuale, distruttiva)"
        @click="onRepair"
      >
        {{ repairing ? 'Riparazione…' : 'Ripara / Reset' }}
      </button>
    </div>

    <!-- Loading / Error -->
    <div v-if="loading" class="vs-loading">Caricamento…</div>
    <div v-if="error" class="vs-error">{{ error }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { vectorStoreApi } from '../../services/api'
import { useSettingsStore } from '../../stores/settings'
import { useServicesStore } from '../../stores/services'
import type { VectorStoreStats } from '../../types/settings'
import UiToggle from '../ui/UiToggle.vue'
import { useModal } from '../../composables/useModal'

const settingsStore = useSettingsStore()
const servicesStore = useServicesStore()
const { confirm } = useModal()

const stats = ref<VectorStoreStats | null>(null)
const loading = ref(false)
const reembedding = ref(false)
const repairing = ref(false)
const error = ref<string | null>(null)

// Effective RAG readiness: prefer the WS-updated store value (live after a
// repair), falling back to the value embedded in the last stats fetch.
const rag = computed(() => servicesStore.knowledge ?? stats.value?.rag ?? null)

async function refreshStats(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    stats.value = await vectorStoreApi.getVectorStoreStats()
    servicesStore.onKnowledgeStatus({ ...stats.value.rag, type: 'knowledge.status' as const })
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
    const result = await vectorStoreApi.reembedTools()
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

async function onRepair(): Promise<void> {
  const ok = await confirm({
    title: 'Ripristina vector store',
    message:
      `Ripristinare il vector store? I dati embedded salvati (memorie/fatti) ` +
      `verranno cancellati e ricreati da zero. L'operazione non è reversibile.`,
    type: 'danger',
    confirmText: 'Ripristina'
  })
  if (!ok) return
  repairing.value = true
  error.value = null
  try {
    stats.value = await vectorStoreApi.repairVectorStore()
    servicesStore.onKnowledgeStatus({ ...stats.value.rag, type: 'knowledge.status' as const })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Errore durante la riparazione'
  } finally {
    repairing.value = false
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
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
  align-items: center;
}

.vs-status__item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.vs-status__item strong {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

.vs-status__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.vs-status__dot--ok {
  background: var(--success);
  box-shadow: 0 0 6px var(--success-glow);
}

.vs-status__dot--off {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger-glow);
}

.vs-status__label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

/* ── Collections ───────────────────────────────────────────── */
.vs-collections {
  margin-bottom: var(--space-3);
}

.vs-collections__header {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-semibold);
  margin-bottom: var(--space-2);
}

.vs-collections__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.vs-coll {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  transition: border-color var(--transition-fast);
}

.vs-coll:hover {
  border-color: var(--accent-border);
}

.vs-coll__name {
  font-size: var(--text-sm);
  color: var(--accent);
  font-weight: var(--weight-medium);
  font-family: var(--font-mono);
  min-width: 120px;
}

.vs-coll__stat {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.vs-coll__stat strong {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

/* ── Section ───────────────────────────────────────────────── */
.vs-section {
  margin-bottom: var(--space-3);
}

.vs-section__header {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-semibold);
  margin-bottom: var(--space-2);
}

/* ── Row (toggle / input) ──────────────────────────────────── */
.vs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
  gap: var(--space-3);
}

.vs-row__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.vs-row__label {
  font-size: var(--text-sm);
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}

.vs-row__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.vs-input-wrap {
  flex-shrink: 0;
}

.vs-input {
  width: 80px;
  padding: var(--space-1) var(--space-2);
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
  transition: border-color var(--transition-fast);
}

.vs-input:focus {
  border-color: var(--accent-border);
}

/* ── Actions ───────────────────────────────────────────────── */
.vs-actions {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.vs-btn {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  border: 1px solid transparent;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.vs-btn--secondary {
  background: var(--surface-2);
  border-color: var(--border);
  color: var(--text-secondary);
}

.vs-btn--secondary:hover:not(:disabled) {
  background: var(--white-light);
  color: var(--text-primary);
}

.vs-btn--accent {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

.vs-btn--accent:hover:not(:disabled) {
  background: var(--accent-light);
  border-color: var(--accent);
}

.vs-btn--danger {
  background: transparent;
  border-color: var(--danger);
  color: var(--danger);
}

.vs-btn--danger:hover:not(:disabled) {
  background: var(--danger-faint);
}

.vs-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── RAG readiness warning ─────────────────────────────────── */
.vs-rag-warn {
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-3);
  background: var(--danger-faint);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.vs-rag-warn strong {
  color: var(--danger);
}

.vs-rag-warn em {
  color: var(--text-primary);
  font-style: normal;
  font-weight: var(--weight-medium);
}

/* ── Empty / Loading / Error ───────────────────────────────── */
.vs-empty {
  color: var(--text-muted);
  padding: var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
}

.vs-loading {
  color: var(--text-muted);
  padding: var(--space-2);
  font-size: var(--text-sm);
}

.vs-error {
  color: var(--danger);
  padding: var(--space-2);
  font-size: var(--text-sm);
  background: var(--danger-faint);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-2);
}
</style>
