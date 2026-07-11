<script setup lang="ts">
/**
 * ModelManager.vue — Full model management panel for LM Studio models.
 *
 * Provides a comprehensive view of all available models with load/unload
 * controls, a load configuration dialog, download section, and status header.
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import type { LMStudioModel } from '../../types/settings'
import AliceSpinner from '../ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import { useModal } from '../../composables/useModal'
import ModelLoadDialog from './ModelLoadDialog.vue'

const settingsStore = useSettingsStore()
const { openCustom } = useModal()

// ── Download section state ──
const downloadModelId = ref('')
const downloadQuantization = ref('')
const isDownloading = ref(false)
const downloadError = ref<string | null>(null)

// ── General error state ──
const errorMessage = ref<string | null>(null)

/** Format bytes to human-readable. */
function formatSize(bytes: number): string {
  const gb = bytes / 1_073_741_824
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / 1_048_576
  if (mb >= 1) return `${mb.toFixed(0)} MB`
  const kb = bytes / 1024
  return `${kb.toFixed(0)} KB`
}

/** Format speed in bytes/s to human-readable. */
function formatSpeed(bps: number): string {
  const mbps = bps / 1_048_576
  if (mbps >= 1) return `${mbps.toFixed(1)} MB/s`
  const kbps = bps / 1024
  return `${kbps.toFixed(0)} KB/s`
}

/** Extract publisher from model name (e.g. "ibm/granite" → "ibm"). */
function getPublisher(name: string): string {
  const idx = name.indexOf('/')
  return idx > 0 ? name.slice(0, idx) : '—'
}

/** Active downloads as array for iteration. */
const activeDownloadsList = computed(() => Array.from(settingsStore.activeDownloads.values()))

/** Download progress percentage. */
function downloadProgress(downloaded?: number, total?: number): number {
  if (!downloaded || !total || total === 0) return 0
  return Math.round((downloaded / total) * 100)
}

/** Open the load configuration dialog for a model. */
async function openLoadDialog(model: LMStudioModel): Promise<void> {
  await openCustom({
    component: ModelLoadDialog,
    props: { model },
    title: `Carica · ${model.display_name || model.name}`,
    width: '480px'
  })
}

/** Unload a model instance. */
async function handleUnload(instanceId: string): Promise<void> {
  errorMessage.value = null
  try {
    await settingsStore.unloadModel(instanceId)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Errore nello scaricamento del modello'
  }
}

/** Start downloading a model. */
async function handleDownload(): Promise<void> {
  if (!downloadModelId.value.trim()) return
  isDownloading.value = true
  downloadError.value = null
  try {
    await settingsStore.downloadModel(
      downloadModelId.value.trim(),
      downloadQuantization.value.trim() || undefined
    )
    downloadModelId.value = ''
    downloadQuantization.value = ''
  } catch (e) {
    downloadError.value = e instanceof Error ? e.message : 'Errore nel download'
  } finally {
    isDownloading.value = false
  }
}

onMounted(() => {
  // Avoid redundant refetch — the store may already be populated by other panels.
  if (settingsStore.models.length === 0) {
    settingsStore.loadModels()
  }
})
</script>

<template>
  <section class="settings-section">
    <!-- ── Header ── -->
    <h3 class="settings-section__title">Gestione Modelli</h3>
    <div class="mm-status-row">
      <span
        class="mm-conn-badge"
        :class="settingsStore.lmStudioConnected ? 'mm-conn-badge--ok' : 'mm-conn-badge--err'"
      >
        <span class="mm-conn-dot" />
        {{ settingsStore.lmStudioConnected ? 'LM Studio connesso' : 'LM Studio disconnesso' }}
      </span>
      <span class="mm-stats">
        <strong>{{ settingsStore.loadedModelCount }}</strong> caricati
        <span class="mm-stats__sep">·</span>
        <strong>{{ settingsStore.models.length }}</strong> disponibili
      </span>
    </div>

    <!-- ── Error banner ── -->
    <div v-if="errorMessage" class="mm-error">
      <span>{{ errorMessage }}</span>
      <button class="mm-error__close" aria-label="Chiudi errore" @click="errorMessage = null">
        <AppIcon name="x" :size="14" />
      </button>
    </div>

    <!-- ── Operation banner ── -->
    <div v-if="settingsStore.isAnyOperationInProgress" class="mm-operation">
      <div class="mm-operation__track">
        <div class="mm-operation__fill" />
      </div>
      <span>{{ settingsStore.operationDescription }}</span>
    </div>

    <!-- ── Loading ── -->
    <div v-if="settingsStore.isLoadingModels" class="mm-loading">
      <AliceSpinner size="sm" label="Caricamento lista modelli…" />
    </div>

    <!-- ── Models list ── -->
    <div v-else class="mm-list">
      <UiEmptyState
        v-if="settingsStore.models.length === 0"
        icon="package"
        title="Nessun modello disponibile"
        subtitle="Verifica la connessione a LM Studio."
        compact
      />

      <div
        v-for="model in settingsStore.models"
        :key="model.name"
        class="mm-model"
        :class="{
          'mm-model--loaded': model.loaded,
          'mm-model--busy':
            settingsStore.isModelLoading(model.name) ||
            model.loaded_instances.some((i) => settingsStore.isInstanceUnloading(i.id))
        }"
      >
        <!-- Name row -->
        <div class="mm-model__name-row">
          <span class="mm-dot" :class="model.loaded ? 'mm-dot--on' : 'mm-dot--off'" />
          <span class="mm-model__name">{{ model.display_name || model.name }}</span>
          <div
            v-if="
              model.capabilities.vision ||
              model.capabilities.thinking ||
              model.capabilities.trained_for_tool_use
            "
            class="mm-model__caps"
          >
            <span v-if="model.capabilities.vision" class="mm-cap" title="Vision">
              <AppIcon name="eye" :size="11" />
            </span>
            <span v-if="model.capabilities.thinking" class="mm-cap" title="Thinking">
              <AppIcon name="thinking-cap" :size="11" />
            </span>
            <span v-if="model.capabilities.trained_for_tool_use" class="mm-cap" title="Tool Use">
              <AppIcon name="tool" :size="11" />
            </span>
          </div>
          <div class="mm-model__actions">
            <button
              v-if="!model.loaded"
              class="mm-btn mm-btn--load"
              :disabled="
                settingsStore.isModelLoading(model.name) || settingsStore.isAnyOperationInProgress
              "
              @click="openLoadDialog(model)"
            >
              {{ settingsStore.isModelLoading(model.name) ? 'Caricamento…' : 'Carica' }}
            </button>
            <button
              v-for="inst in model.loaded_instances"
              :key="inst.id"
              class="mm-btn mm-btn--unload"
              :disabled="
                settingsStore.isInstanceUnloading(inst.id) || settingsStore.isAnyOperationInProgress
              "
              @click="handleUnload(inst.id)"
            >
              {{ settingsStore.isInstanceUnloading(inst.id) ? 'Scaricamento…' : 'Scarica' }}
            </button>
          </div>
        </div>

        <!-- Meta row -->
        <div class="mm-model__meta">
          <span>{{ getPublisher(model.name) }}</span>
          <span v-if="model.architecture">{{ model.architecture }}</span>
          <span v-if="model.params_string" class="mm-model__params">{{ model.params_string }}</span>
          <span>{{ formatSize(model.size) }}</span>
          <span v-if="model.quantization?.name">{{ model.quantization.name }}</span>
          <span v-if="model.format">{{ model.format.toUpperCase() }}</span>
          <span>ctx {{ model.max_context_length.toLocaleString() }}</span>
        </div>

        <!-- Loaded instances detail -->
        <div v-if="model.loaded_instances.length > 0" class="mm-model__instances">
          <div v-for="inst in model.loaded_instances" :key="inst.id" class="mm-instance">
            <span class="mm-instance__id">{{ inst.id.slice(0, 12) }}…</span>
            <span>ctx {{ inst.config.context_length.toLocaleString() }}</span>
            <span v-if="inst.config.flash_attention" class="mm-instance__cap">
              <AppIcon name="lightning-flash" :size="11" />Flash Attn
            </span>
            <span v-if="inst.config.eval_batch_size">
              batch {{ inst.config.eval_batch_size }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Download Section ── -->
    <div class="mm-download">
      <h4 class="mm-download__title">Scarica nuovo modello</h4>
      <div class="mm-download__form">
        <input
          v-model="downloadModelId"
          class="mm-input"
          type="text"
          placeholder="Identificativo modello (es. ibm/granite-4-micro)"
          @keyup.enter="handleDownload"
        />
        <input
          v-model="downloadQuantization"
          class="mm-input mm-input--narrow"
          type="text"
          placeholder="Quantizzazione (opzionale)"
        />
        <button
          class="mm-btn mm-btn--primary"
          :disabled="!downloadModelId.trim() || isDownloading"
          @click="handleDownload"
        >
          {{ isDownloading ? 'Avvio…' : 'Scarica' }}
        </button>
      </div>
      <div v-if="downloadError" class="mm-download__error">{{ downloadError }}</div>

      <!-- Active downloads -->
      <div v-if="activeDownloadsList.length > 0" class="mm-download__active">
        <div v-for="dl in activeDownloadsList" :key="dl.job_id" class="mm-dl">
          <div class="mm-dl__header">
            <span class="mm-dl__id">{{ dl.job_id }}</span>
            <span class="mm-dl__status" :class="`mm-dl__status--${dl.status}`">{{
              dl.status
            }}</span>
          </div>
          <div class="mm-dl__track">
            <div
              class="mm-dl__fill"
              :style="{ width: downloadProgress(dl.downloaded_bytes, dl.total_size_bytes) + '%' }"
            />
          </div>
          <div class="mm-dl__footer">
            <span class="mm-dl__pct">
              {{ downloadProgress(dl.downloaded_bytes, dl.total_size_bytes) }}%
            </span>
            <span v-if="dl.downloaded_bytes != null && dl.total_size_bytes">
              {{ formatSize(dl.downloaded_bytes) }} / {{ formatSize(dl.total_size_bytes) }}
            </span>
            <span v-if="dl.bytes_per_second">{{ formatSpeed(dl.bytes_per_second) }}</span>
            <span v-if="dl.estimated_completion">ETA: {{ dl.estimated_completion }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ── Shared settings section typography (mirrors VoiceSettings) ── */
.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

/* ── Section header ── */
.mm-status-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
}

.mm-conn-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  font-size: var(--text-xs);
  padding: var(--space-0-5) var(--space-2);
  border-radius: var(--radius-sm);
}

.mm-conn-badge--ok {
  color: var(--success);
  background: var(--success-light);
}

.mm-conn-badge--err {
  color: var(--danger);
  background: var(--danger-faint);
  border: 1px solid var(--danger-border);
}

.mm-conn-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: currentColor;
}

.mm-stats {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.mm-stats strong {
  color: var(--text-secondary);
}

.mm-stats__sep {
  margin: 0 var(--space-1);
  opacity: 0.5;
}

/* ── Error banner ── */
.mm-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--danger-faint);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-sm);
  color: var(--danger);
  font-size: var(--text-sm);
  margin-bottom: var(--space-3);
}

.mm-error__close {
  background: none;
  border: none;
  color: var(--danger);
  cursor: pointer;
  padding: 0;
  line-height: 1;
  flex-shrink: 0;
  opacity: var(--opacity-medium);
  transition: opacity var(--transition-fast);
}

.mm-error__close:hover {
  opacity: 1;
}

/* ── Operation banner ── */
.mm-operation {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--accent-faint);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--accent);
  margin-bottom: var(--space-3);
}

.mm-operation__track {
  flex: 1;
  height: 2px;
  background: var(--border);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.mm-operation__fill {
  height: 100%;
  width: 40%;
  background: var(--accent);
  border-radius: var(--radius-pill);
  animation: mmOpProgress 1.2s ease-in-out infinite;
}

@keyframes mmOpProgress {
  0% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(350%);
  }
}

/* ── Loading / empty ── */
.mm-loading {
  display: flex;
  justify-content: center;
  padding: var(--space-8);
}

/* ── Model list ── */
.mm-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
  margin-bottom: var(--space-5);
}

/* ── Model item ── */
.mm-model {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-1);
  border-radius: var(--radius-md);
  transition:
    background var(--transition-fast),
    opacity var(--transition-fast);
}

.mm-model:hover {
  background: var(--surface-2);
}

.mm-model--busy {
  opacity: var(--opacity-soft);
}

/* ── Name row ── */
.mm-model__name-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.mm-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.mm-dot--on {
  background: var(--success);
  box-shadow: 0 0 5px var(--success-glow);
}

.mm-dot--off {
  background: var(--border-hover);
}

.mm-model__name {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Capability icons ── */
.mm-model__caps {
  display: flex;
  gap: 3px;
}

.mm-cap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: var(--white-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: default;
  flex-shrink: 0;
}

/* ── Actions ── */
.mm-model__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  flex-shrink: 0;
  margin-left: auto;
}

/* ── Meta row ── */
.mm-model__meta {
  display: flex;
  align-items: center;
  gap: 0;
  flex-wrap: wrap;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  padding-left: calc(7px + var(--space-2));
}

.mm-model__meta > span {
  padding-right: var(--space-1-5);
}

.mm-model__meta > span + span::before {
  content: '·';
  margin-right: var(--space-1-5);
  opacity: 0.4;
}

.mm-model__params {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

/* ── Instances ── */
.mm-model__instances {
  padding-left: calc(7px + var(--space-2));
  padding-top: var(--space-1-5);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mm-instance {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.mm-instance__id {
  font-family: var(--font-mono);
  opacity: 0.7;
}

.mm-instance__cap {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  opacity: var(--opacity-medium);
}

/* ── Buttons ── */
.mm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-1) var(--space-2-5);
  font-size: var(--text-xs);
  font-family: var(--font-sans);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
  background: transparent;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}

.mm-btn:disabled {
  opacity: var(--opacity-dim);
  cursor: not-allowed;
  pointer-events: none;
}

.mm-btn--load {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-faint);
}

.mm-btn--load:hover:not(:disabled) {
  background: var(--accent-dim);
}

.mm-btn--unload {
  border-color: var(--danger-border);
  color: var(--danger);
}

.mm-btn--unload:hover:not(:disabled) {
  background: var(--danger-faint);
}

.mm-btn--primary {
  border-color: var(--accent-border);
  background: var(--accent-dim);
  color: var(--accent);
}

.mm-btn--primary:hover:not(:disabled) {
  background: var(--accent);
  color: var(--bg-primary);
}

.mm-btn--ghost {
  border-color: var(--border);
  color: var(--text-secondary);
}

.mm-btn--ghost:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

/* ── Download section ── */
.mm-download {
  background: var(--surface-1);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.mm-download__title {
  margin: 0 0 var(--space-3) 0;
  font-family: var(--font-display);
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.mm-download__form {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.mm-input {
  flex: 1;
  min-width: 200px;
  padding: var(--space-1-5) var(--space-3);
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--transition-fast);
}

.mm-input:focus {
  border-color: var(--accent-border);
}

.mm-input::placeholder {
  color: var(--text-muted);
}

.mm-input--narrow {
  min-width: 140px;
  flex: 0.4;
}

.mm-download__error {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--danger);
}

.mm-download__active {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── Download item ── */
.mm-dl {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-sm);
}

.mm-dl__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.mm-dl__id {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.mm-dl__status {
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: var(--space-px) var(--space-1-5);
  border-radius: var(--radius-sm);
}

.mm-dl__status--downloading {
  color: var(--accent);
  background: var(--accent-dim);
}

.mm-dl__status--completed,
.mm-dl__status--already_downloaded {
  color: var(--success);
  background: var(--success-light);
}

.mm-dl__status--paused {
  color: var(--text-secondary);
  background: var(--surface-hover);
}

.mm-dl__status--failed {
  color: var(--danger);
  background: var(--danger-faint);
}

.mm-dl__track {
  height: 2px;
  background: var(--border);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.mm-dl__fill {
  height: 100%;
  background: var(--accent);
  border-radius: var(--radius-pill);
  transition: width 0.3s ease;
}

.mm-dl__footer {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  flex-wrap: wrap;
}

.mm-dl__pct {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}
</style>
