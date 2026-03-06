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

const settingsStore = useSettingsStore()

// ── Load configuration dialog state ──
const showLoadDialog = ref(false)
const loadDialogModel = ref<LMStudioModel | null>(null)
const loadContextLength = ref(4096)
const loadFlashAttention = ref(false)

// ── Download section state ──
const downloadModelId = ref('')
const downloadQuantization = ref('')
const isDownloading = ref(false)
const downloadError = ref<string | null>(null)

/** Estimated VRAM usage for the model being configured in load dialog. */
const estimatedVram = computed(() => {
    if (!loadDialogModel.value) return ''
    const baseGb = loadDialogModel.value.size / 1_073_741_824
    // KV cache rough estimate: ~0.5GB per 4096 tokens for typical models
    const kvEstimate = (loadContextLength.value / 4096) * 0.5
    const total = baseGb + kvEstimate
    return total.toFixed(1)
})

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
function openLoadDialog(model: LMStudioModel): void {
    loadDialogModel.value = model
    loadContextLength.value = Math.min(model.max_context_length, 8192)
    loadFlashAttention.value = false
    showLoadDialog.value = true
}

/** Confirm loading a model with configuration. */
async function confirmLoad(): Promise<void> {
    if (!loadDialogModel.value) return
    errorMessage.value = null
    try {
        await settingsStore.loadModel(loadDialogModel.value.name, {
            context_length: loadContextLength.value,
            flash_attention: loadFlashAttention.value
        })
        showLoadDialog.value = false
    } catch (e) {
        errorMessage.value = e instanceof Error ? e.message : 'Errore nel caricamento del modello'
    }
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

/** Set a model as active. */
async function setActive(modelName: string): Promise<void> {
    errorMessage.value = null
    try {
        await settingsStore.switchModel(modelName)
    } catch (e) {
        errorMessage.value = e instanceof Error ? e.message : 'Errore nel cambio modello'
    }
}

onMounted(() => {
    settingsStore.loadModels()
})
</script>

<template>
    <div class="model-manager">
        <!-- ── Status Header ── -->
        <div class="mm-header">
            <div class="mm-header__title">
                <h3>Gestione Modelli</h3>
                <span class="mm-header__status"
                    :class="settingsStore.lmStudioConnected ? 'mm-header__status--ok' : 'mm-header__status--err'">
                    <span class="mm-header__dot" />
                    {{ settingsStore.lmStudioConnected ? 'LM Studio connesso' : 'LM Studio disconnesso' }}
                </span>
            </div>
            <div class="mm-header__stats">
                <span class="mm-header__stat">
                    <strong>{{ settingsStore.loadedModelCount }}</strong> caricati
                </span>
                <span class="mm-header__stat-sep">·</span>
                <span class="mm-header__stat">
                    <strong>{{ settingsStore.models.length }}</strong> disponibili
                </span>
            </div>
        </div>

        <!-- ── Error banner ── -->
        <div v-if="errorMessage" class="mm-error">
            {{ errorMessage }}
            <button class="mm-error__close" aria-label="Chiudi errore" @click="errorMessage = null">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        </div>

        <!-- Global operation in progress -->
        <div v-if="settingsStore.isAnyOperationInProgress" class="mm-operation">
            <div class="mm-operation__bar">
                <div class="mm-operation__bar-fill" />
            </div>
            <span class="mm-operation__text">{{ settingsStore.operationDescription }}</span>
        </div>

        <!-- ── Loading spinner ── -->
        <div v-if="settingsStore.isLoadingModels" class="mm-loading">
            <span class="mm-spinner" />
            <span>Caricamento lista modelli…</span>
        </div>

        <!-- ── Models List ── -->
        <div v-else class="mm-models">
            <div v-if="settingsStore.models.length === 0" class="mm-empty">
                Nessun modello disponibile. Verifica la connessione a LM Studio.
            </div>

            <div v-for="model in settingsStore.models" :key="model.name" class="mm-model" :class="{
                'mm-model--active': model.is_active,
                'mm-model--loaded': model.loaded,
                'mm-model--loading': settingsStore.isModelLoading(model.name),
                'mm-model--unloading': model.loaded_instances.some(i => settingsStore.isInstanceUnloading(i.id))
            }">
                <div class="mm-model__accent-bar" v-if="model.loaded" />
                <div class="mm-model__header">
                    <div class="mm-model__info">
                        <span class="mm-model__load-dot"
                            :class="model.loaded ? 'mm-model__load-dot--on' : 'mm-model__load-dot--off'" />
                        <span class="mm-model__name">{{ model.display_name || model.name }}</span>
                        <span v-if="model.is_active" class="mm-model__active-badge">Attivo</span>
                    </div>
                    <div class="mm-model__actions">
                        <button v-if="!model.is_active" class="mm-btn mm-btn--ghost mm-btn--sm"
                            :disabled="settingsStore.isAnyOperationInProgress" @click="setActive(model.name)">
                            Imposta attivo
                        </button>
                        <button v-if="!model.loaded" class="mm-btn mm-btn--primary mm-btn--sm"
                            :disabled="settingsStore.isModelLoading(model.name) || settingsStore.isAnyOperationInProgress"
                            @click="openLoadDialog(model)">
                            {{ settingsStore.isModelLoading(model.name) ? 'Caricamento…' : 'Carica' }}
                        </button>
                        <button v-for="inst in model.loaded_instances" :key="inst.id"
                            class="mm-btn mm-btn--danger mm-btn--sm"
                            :disabled="settingsStore.isInstanceUnloading(inst.id) || settingsStore.isAnyOperationInProgress"
                            @click="handleUnload(inst.id)">
                            {{ settingsStore.isInstanceUnloading(inst.id) ? 'Scaricamento…' : 'Scarica' }}
                        </button>
                    </div>
                </div>

                <div class="mm-model__meta">
                    <span class="mm-model__meta-item" title="Editore">{{ getPublisher(model.name) }}</span>
                    <span v-if="model.architecture" class="mm-model__meta-item" title="Architettura">{{
                        model.architecture }}</span>
                    <span v-if="model.params_string" class="mm-model__meta-item mm-model__meta-item--accent">{{
                        model.params_string }}</span>
                    <span class="mm-model__meta-item">{{ formatSize(model.size) }}</span>
                    <span v-if="model.quantization?.name" class="mm-model__meta-item">{{ model.quantization.name
                    }}</span>
                    <span v-if="model.format" class="mm-model__meta-item">{{ model.format.toUpperCase() }}</span>
                    <span class="mm-model__meta-item">ctx {{ model.max_context_length.toLocaleString() }}</span>
                </div>

                <!-- Capabilities -->
                <div v-if="model.capabilities.vision || model.capabilities.thinking || model.capabilities.trained_for_tool_use"
                    class="mm-model__caps">
                    <span v-if="model.capabilities.vision" class="mm-cap">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                            <circle cx="12" cy="12" r="3" />
                        </svg>
                        Vision
                    </span>
                    <span v-if="model.capabilities.thinking" class="mm-cap">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path
                                d="M12 2a7 7 0 0 0-4.6 12.3c.6.5 1 1.2 1.1 2V17h7v-.7c.2-.8.5-1.5 1.1-2A7 7 0 0 0 12 2z" />
                            <path d="M10 21h4" />
                            <path d="M9 17h6" />
                        </svg>
                        Thinking
                    </span>
                    <span v-if="model.capabilities.trained_for_tool_use" class="mm-cap">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path
                                d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                        </svg>
                        Tool Use
                    </span>
                </div>

                <!-- Loaded instances detail -->
                <div v-if="model.loaded_instances.length > 0" class="mm-model__instances">
                    <div v-for="inst in model.loaded_instances" :key="inst.id" class="mm-instance">
                        <span class="mm-instance__id">{{ inst.id.slice(0, 12) }}…</span>
                        <span class="mm-instance__detail">ctx {{ inst.config.context_length.toLocaleString() }}</span>
                        <span v-if="inst.config.flash_attention" class="mm-instance__detail">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                            </svg>
                            Flash Attn
                        </span>
                        <span v-if="inst.config.eval_batch_size" class="mm-instance__detail">batch {{
                            inst.config.eval_batch_size }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- ── Download Section ── -->
        <div class="mm-download">
            <h4 class="mm-download__title">Scarica nuovo modello</h4>
            <div class="mm-download__form">
                <input v-model="downloadModelId" class="mm-input" type="text"
                    placeholder="Identificativo modello (es. ibm/granite-4-micro)" @keyup.enter="handleDownload" />
                <input v-model="downloadQuantization" class="mm-input mm-input--small" type="text"
                    placeholder="Quantizzazione (opzionale)" />
                <button class="mm-btn mm-btn--primary" :disabled="!downloadModelId.trim() || isDownloading"
                    @click="handleDownload">
                    {{ isDownloading ? 'Avvio…' : 'Scarica' }}
                </button>
            </div>
            <div v-if="downloadError" class="mm-download__error">{{ downloadError }}</div>

            <!-- Active downloads -->
            <div v-if="activeDownloadsList.length > 0" class="mm-download__active">
                <div v-for="dl in activeDownloadsList" :key="dl.job_id" class="mm-dl-item">
                    <div class="mm-dl-item__header">
                        <span class="mm-dl-item__id">{{ dl.job_id }}</span>
                        <span class="mm-dl-item__status" :class="`mm-dl-item__status--${dl.status}`">
                            {{ dl.status }}
                        </span>
                    </div>
                    <div class="mm-dl-item__bar-container">
                        <div class="mm-dl-item__bar"
                            :style="{ width: downloadProgress(dl.downloaded_bytes, dl.total_size_bytes) + '%' }" />
                    </div>
                    <span class="mm-dl-item__percent">
                        {{ downloadProgress(dl.downloaded_bytes, dl.total_size_bytes) }}%
                    </span>
                    <div class="mm-dl-item__details">
                        <span v-if="dl.downloaded_bytes != null && dl.total_size_bytes">
                            {{ formatSize(dl.downloaded_bytes) }} / {{ formatSize(dl.total_size_bytes) }}
                        </span>
                        <span v-if="dl.bytes_per_second">{{ formatSpeed(dl.bytes_per_second) }}</span>
                        <span v-if="dl.estimated_completion">ETA: {{ dl.estimated_completion }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- ── Load Configuration Dialog ── -->
        <Teleport to="body">
            <Transition name="dialog">
                <div v-if="showLoadDialog && loadDialogModel" class="mm-overlay" @click.self="showLoadDialog = false"
                    @keydown.escape="showLoadDialog = false">
                    <div class="mm-dialog" role="dialog" aria-modal="true" aria-labelledby="mm-dialog-title">
                        <h4 id="mm-dialog-title" class="mm-dialog__title">Carica modello</h4>
                        <p class="mm-dialog__subtitle">{{ loadDialogModel.display_name || loadDialogModel.name }}</p>

                        <label class="mm-dialog__label">
                            Lunghezza contesto
                            <span class="mm-dialog__label-value">{{ loadContextLength.toLocaleString() }}</span>
                        </label>
                        <input v-model.number="loadContextLength" type="range" class="mm-dialog__slider" :min="512"
                            :max="loadDialogModel.max_context_length" :step="256" />
                        <div class="mm-dialog__range-labels">
                            <span>512</span>
                            <span>{{ loadDialogModel.max_context_length.toLocaleString() }}</span>
                        </div>

                        <div class="mm-dialog__vram">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="2" y="6" width="20" height="12" rx="2" />
                                <line x1="6" y1="10" x2="6" y2="14" />
                                <line x1="10" y1="10" x2="10" y2="14" />
                                <line x1="14" y1="10" x2="14" y2="14" />
                                <line x1="18" y1="10" x2="18" y2="14" />
                            </svg>
                            <span>VRAM stimata: ~{{ estimatedVram }} GB</span>
                            <span class="mm-dialog__vram-base">(modello: {{ formatSize(loadDialogModel.size) }})</span>
                        </div>

                        <label class="mm-dialog__toggle">
                            <input v-model="loadFlashAttention" type="checkbox" />
                            <span>Flash Attention</span>
                        </label>

                        <div class="mm-dialog__actions">
                            <button class="mm-btn mm-btn--ghost" @click="showLoadDialog = false">Annulla</button>
                            <button class="mm-btn mm-btn--primary"
                                :disabled="(loadDialogModel ? settingsStore.isModelLoading(loadDialogModel.name) : false) || settingsStore.isAnyOperationInProgress"
                                @click="confirmLoad">
                                {{ loadDialogModel && settingsStore.isModelLoading(loadDialogModel.name) ?
                                    'Caricamento…' : 'Carica' }}
                            </button>
                        </div>
                    </div>
                </div>
            </Transition>
        </Teleport>
    </div>
</template>

<style scoped>
.model-manager {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
}

/* ── Header ── */
.mm-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-2);
}

.mm-header__title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
}

.mm-header__title h3 {
    margin: 0;
    font-size: var(--text-lg);
    color: var(--text-primary);
}

.mm-header__status {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    font-size: var(--text-sm);
    padding: var(--space-0-5) var(--space-2);
    border-radius: var(--radius-sm);
}

.mm-header__status--ok {
    color: var(--success);
    background: var(--success-light);
}

.mm-header__status--err {
    color: var(--danger);
    background: var(--danger-hover);
}

.mm-header__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: currentColor;
}

.mm-header__stats {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    color: var(--text-secondary);
    font-size: var(--text-base);
}

.mm-header__stat strong {
    color: var(--text-primary);
}

.mm-header__stat-sep {
    color: var(--text-muted);
}

/* ── Error ── */
.mm-error {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2-5) 14px;
    background: var(--danger-hover);
    border: 1px solid var(--danger);
    border-radius: var(--radius-sm);
    color: var(--danger);
    font-size: var(--text-base);
}

.mm-error__close {
    background: none;
    border: none;
    color: var(--danger);
    cursor: pointer;
    font-size: var(--text-md);
    padding: 0 var(--space-1);
}

/* ── Loading ── */
.mm-loading {
    display: flex;
    align-items: center;
    gap: var(--space-2-5);
    padding: var(--space-6);
    color: var(--text-secondary);
    font-size: var(--text-base);
    justify-content: center;
}

.mm-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: var(--radius-full);
    animation: mm-spin 0.6s linear infinite;
}

@keyframes mm-spin {
    to {
        transform: rotate(360deg);
    }
}

.mm-empty {
    padding: var(--space-6);
    text-align: center;
    color: var(--text-muted);
    font-size: var(--text-base);
}

/* ── Models List ── */
.mm-models {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

.mm-model {
    position: relative;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    transition: border-color var(--transition-fast), box-shadow var(--transition-fast), opacity var(--transition-fast);
}

.mm-model:hover {
    border-color: var(--border-hover);
}

.mm-model--active {
    border-color: var(--accent-border);
}

.mm-model--loaded {
    background: linear-gradient(135deg, var(--bg-tertiary), var(--success-faint));
    border-radius: 2px var(--radius-md) var(--radius-md) 2px;
}

.mm-model--loading {
    animation: mmLoadPulse 1.8s ease-in-out infinite;
    border-color: var(--accent-border);
}

@keyframes mmLoadPulse {

    0%,
    100% {
        box-shadow: 0 0 0 0 transparent;
    }

    50% {
        box-shadow: 0 0 12px var(--accent-glow);
    }
}

.mm-model--unloading {
    opacity: var(--opacity-soft);
    animation: mmUnloadFade 1s ease-in-out infinite alternate;
}

@keyframes mmUnloadFade {
    from {
        opacity: 0.6;
    }

    to {
        opacity: 0.35;
    }
}

.mm-model__accent-bar {
    position: absolute;
    left: 0;
    top: 4px;
    bottom: 4px;
    width: 3px;
    border-radius: 0 2px 2px 0;
    background: var(--success);
    box-shadow: 0 0 6px var(--success-glow);
}

.mm-model__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
}

.mm-model__info {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
}

.mm-model__load-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    flex-shrink: 0;
}

.mm-model__load-dot--on {
    background: var(--success);
    box-shadow: 0 0 6px var(--success-glow);
}

.mm-model__load-dot--off {
    background: var(--text-muted);
}

.mm-model__name {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.mm-model__active-badge {
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--accent);
    background: var(--accent-dim);
    padding: var(--space-px) var(--space-1-5);
    border-radius: var(--radius-sm);
}

.mm-model__actions {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    flex-shrink: 0;
}

.mm-model__meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    margin-top: var(--space-2);
}

.mm-model__meta-item {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    padding: var(--space-px) var(--space-1-5);
    border-radius: var(--radius-sm);
}

.mm-model__meta-item--accent {
    color: var(--accent);
    font-weight: var(--weight-semibold);
}

.mm-model__caps {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-1-5);
}

.mm-cap {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-0-5) var(--space-2);
    background: var(--white-subtle);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    transition: all var(--transition-fast);
}

.mm-cap svg {
    flex-shrink: 0;
    opacity: var(--opacity-medium);
}

/* ── Loaded instances ── */
.mm-model__instances {
    margin-top: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--border);
}

.mm-instance {
    display: flex;
    align-items: center;
    gap: var(--space-2-5);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    padding: var(--space-0-5) 0;
}

.mm-instance__id {
    font-family: var(--font-mono);
    color: var(--text-muted);
}

.mm-instance__detail {
    display: inline-flex;
    align-items: center;
    gap: 3px;
}

.mm-instance__detail svg {
    flex-shrink: 0;
    opacity: var(--opacity-medium);
}

/* ── Buttons ── */
.mm-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-1-5) 14px;
    font-size: var(--text-base);
    font-family: var(--font-sans);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
    white-space: nowrap;
    transition: all var(--transition-fast);
}

.mm-btn--sm {
    padding: 3px var(--space-2-5);
    font-size: var(--text-sm);
}

.mm-btn--primary {
    background: var(--accent-dim);
    border-color: var(--accent-border);
    color: var(--accent);
}

.mm-btn--primary:hover {
    background: var(--accent);
    color: var(--bg-primary);
}

.mm-btn--ghost {
    background: transparent;
    border-color: var(--border);
    color: var(--text-secondary);
}

.mm-btn--ghost:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
}

.mm-btn--danger {
    background: transparent;
    border-color: var(--danger);
    color: var(--danger);
}

.mm-btn--danger:hover {
    background: var(--danger-hover);
}

.mm-btn:disabled {
    opacity: var(--opacity-dim);
    cursor: not-allowed;
    pointer-events: none;
}

/* ── Download Section ── */
.mm-download {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
}

.mm-download__title {
    margin: 0 0 var(--space-3) 0;
    font-size: var(--text-md);
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
    padding: 7px var(--space-3);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: var(--text-base);
    outline: none;
    transition: border-color var(--transition-fast);
}

.mm-input:focus {
    border-color: var(--accent-border);
}

.mm-input::placeholder {
    color: var(--text-muted);
}

.mm-input--small {
    min-width: 140px;
    flex: 0.4;
}

.mm-download__error {
    margin-top: var(--space-2);
    color: var(--danger);
    font-size: var(--text-sm);
}

.mm-download__active {
    margin-top: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

/* ── Download item ── */
.mm-dl-item {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--space-2-5) var(--space-3);
}

.mm-dl-item__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-1-5);
}

.mm-dl-item__id {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    font-family: var(--font-mono);
}

.mm-dl-item__status {
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: var(--space-px) var(--space-1-5);
    border-radius: var(--radius-sm);
}

.mm-dl-item__status--downloading {
    color: var(--accent);
    background: var(--accent-dim);
}

.mm-dl-item__status--paused {
    color: var(--text-secondary);
    background: var(--bg-tertiary);
}

.mm-dl-item__status--completed {
    color: var(--success);
    background: var(--success-light);
}

.mm-dl-item__status--failed {
    color: var(--danger);
    background: var(--danger-hover);
}

.mm-dl-item__bar-container {
    height: var(--space-1);
    background: var(--bg-primary);
    border-radius: var(--space-0-5);
    overflow: hidden;
}

.mm-dl-item__bar {
    height: 100%;
    background: linear-gradient(90deg, var(--accent) 0%, var(--accent-hover) 50%, var(--accent) 100%);
    background-size: 200% 100%;
    animation: mmShimmer 1.5s ease-in-out infinite;
    border-radius: var(--space-0-5);
    transition: width 0.3s ease;
}

@keyframes mmShimmer {
    0% {
        background-position: 200% 0;
    }

    100% {
        background-position: -200% 0;
    }
}

.mm-dl-item__percent {
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    color: var(--accent);
    margin-top: var(--space-0-5);
}

.mm-dl-item__details {
    display: flex;
    gap: var(--space-3);
    margin-top: var(--space-1);
    font-size: var(--text-xs);
    color: var(--text-muted);
}

.mm-dl-item__status--already_downloaded {
    color: var(--success);
    background: var(--success-light);
}

/* ── Dialog Overlay ── */
.mm-overlay {
    position: fixed;
    inset: 0;
    background: var(--black-heavy);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--z-overlay);
}

.mm-dialog {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-6);
    width: 400px;
    max-width: 90vw;
    box-shadow: var(--shadow-md);
}

.mm-dialog__title {
    margin: 0 0 var(--space-1) 0;
    font-size: var(--text-lg);
    color: var(--text-primary);
}

.mm-dialog__subtitle {
    margin: 0 0 var(--space-4) 0;
    font-size: var(--text-base);
    color: var(--text-secondary);
}

.mm-dialog__label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: var(--text-base);
    color: var(--text-secondary);
    margin-bottom: var(--space-1-5);
}

.mm-dialog__label-value {
    color: var(--accent);
    font-weight: var(--weight-semibold);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
}

.mm-dialog__slider {
    width: 100%;
    accent-color: var(--accent);
    margin-bottom: var(--space-1);
}

.mm-dialog__range-labels {
    display: flex;
    justify-content: space-between;
    font-size: var(--text-2xs);
    color: var(--text-muted);
    margin-bottom: 14px;
}

.mm-dialog__vram {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: var(--space-2) var(--space-2-5);
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    color: var(--accent);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    margin-bottom: 14px;
}

.mm-dialog__vram svg {
    flex-shrink: 0;
    opacity: var(--opacity-medium);
}

.mm-dialog__vram-base {
    color: var(--text-secondary);
    font-weight: var(--weight-normal);
}

.mm-dialog__toggle {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-base);
    color: var(--text-secondary);
    cursor: pointer;
    margin-bottom: var(--space-4);
}

.mm-dialog__toggle input {
    accent-color: var(--accent);
}

.mm-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
}

/* ── Dialog transition ── */
.dialog-enter-active,
.dialog-leave-active {
    transition: opacity var(--transition-normal);
}

.dialog-enter-active .mm-dialog,
.dialog-leave-active .mm-dialog {
    transition: transform var(--transition-normal);
}

.dialog-enter-from,
.dialog-leave-to {
    opacity: 0;
}

.dialog-enter-from .mm-dialog {
    transform: scale(0.95) translateY(10px);
}

.dialog-leave-to .mm-dialog {
    transform: scale(0.95) translateY(10px);
}

/* ── Global operation banner ── */
.mm-operation {
    display: flex;
    flex-direction: column;
    gap: var(--space-1-5);
    padding: var(--space-2-5) 14px;
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
}

.mm-operation__bar {
    height: 3px;
    background: var(--bg-primary);
    border-radius: var(--space-0-5);
    overflow: hidden;
}

.mm-operation__bar-fill {
    height: 100%;
    width: 40%;
    background: linear-gradient(90deg, var(--accent), var(--accent-hover));
    border-radius: var(--space-0-5);
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

.mm-operation__text {
    font-size: var(--text-sm);
    color: var(--accent);
    text-align: center;
    font-weight: var(--weight-medium);
}
</style>
