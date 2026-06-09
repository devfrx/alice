<script setup lang="ts">
/**
 * ModelLoadDialog — Load configuration form for an LM Studio model.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (loaded successfully) or `false` (cancelled).
 * Load errors are shown inline rather than in an outside banner.
 */
import { computed, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import type { LMStudioModel } from '../../types/settings'
import AppIcon from '../ui/AppIcon.vue'
import UiCheckbox from '../ui/UiCheckbox.vue'

const props = defineProps<{
    model: LMStudioModel
}>()

const emit = defineEmits<{ close: [result: boolean] }>()

const settingsStore = useSettingsStore()

const loadContextLength = ref(Math.min(props.model.max_context_length, 8192))
const loadFlashAttention = ref(false)
const errorMessage = ref<string | null>(null)

/** Estimated VRAM usage for the model being configured. */
const estimatedVram = computed(() => {
    const baseGb = props.model.size / 1_073_741_824
    // KV cache rough estimate: ~0.5GB per 4096 tokens for typical models
    const kvEstimate = (loadContextLength.value / 4096) * 0.5
    const total = baseGb + kvEstimate
    return total.toFixed(1)
})

function formatSize(bytes: number): string {
    const gb = bytes / 1_073_741_824
    if (gb >= 1) return `${gb.toFixed(1)} GB`
    const mb = bytes / 1_048_576
    if (mb >= 1) return `${mb.toFixed(0)} MB`
    const kb = bytes / 1024
    return `${kb.toFixed(0)} KB`
}

async function confirmLoad(): Promise<void> {
    errorMessage.value = null
    try {
        await settingsStore.loadModel(props.model.name, {
            context_length: loadContextLength.value,
            flash_attention: loadFlashAttention.value,
        })
        emit('close', true)
    } catch (e) {
        errorMessage.value = e instanceof Error ? e.message : 'Errore nel caricamento del modello'
    }
}
</script>

<template>
    <div class="model-load-dialog">
        <p class="model-load-dialog__subtitle">{{ model.display_name || model.name }}</p>

        <!-- Inline error -->
        <div v-if="errorMessage" class="model-load-dialog__error">
            <span>{{ errorMessage }}</span>
            <button class="model-load-dialog__error-close" aria-label="Chiudi errore"
                @click="errorMessage = null">
                <AppIcon name="x" :size="14" />
            </button>
        </div>

        <label class="model-load-dialog__label">
            Lunghezza contesto
            <span class="model-load-dialog__label-val">{{ loadContextLength.toLocaleString() }}</span>
        </label>
        <input v-model.number="loadContextLength" type="range" class="model-load-dialog__slider"
            :min="512" :max="model.max_context_length" :step="256" />
        <div class="model-load-dialog__range-labels">
            <span>512</span>
            <span>{{ model.max_context_length.toLocaleString() }}</span>
        </div>

        <div class="model-load-dialog__vram">
            <AppIcon name="chip" :size="14" />
            <span>VRAM stimata: ~{{ estimatedVram }} GB</span>
            <span class="model-load-dialog__vram-base">(modello: {{ formatSize(model.size) }})</span>
        </div>

        <UiCheckbox v-model="loadFlashAttention" label="Flash Attention" />

        <div class="model-load-dialog__actions">
            <button class="mm-btn mm-btn--ghost" @click="emit('close', false)">Annulla</button>
            <button class="mm-btn mm-btn--primary"
                :disabled="settingsStore.isModelLoading(model.name) || settingsStore.isAnyOperationInProgress"
                @click="confirmLoad">
                {{ settingsStore.isModelLoading(model.name) ? 'Caricamento…' : 'Carica' }}
            </button>
        </div>
    </div>
</template>

<style scoped>
.model-load-dialog {
    display: flex;
    flex-direction: column;
}

.model-load-dialog__subtitle {
    margin: 0 0 var(--space-5) 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
    font-family: var(--font-mono);
}

/* ── Inline error ── */
.model-load-dialog__error {
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

.model-load-dialog__error-close {
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

.model-load-dialog__error-close:hover {
    opacity: 1;
}

.model-load-dialog__label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin-bottom: var(--space-1-5);
}

.model-load-dialog__label-val {
    color: var(--accent);
    font-weight: var(--weight-semibold);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
}

.model-load-dialog__slider {
    width: 100%;
    accent-color: var(--accent);
    margin-bottom: var(--space-1);
}

.model-load-dialog__range-labels {
    display: flex;
    justify-content: space-between;
    font-size: var(--text-2xs);
    color: var(--text-muted);
    margin-bottom: var(--space-4);
}

.model-load-dialog__vram {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: var(--space-2) var(--space-3);
    background: var(--accent-faint);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    color: var(--accent);
    font-size: var(--text-sm);
    margin-bottom: var(--space-4);
}

.model-load-dialog__vram svg {
    flex-shrink: 0;
    opacity: var(--opacity-medium);
}

.model-load-dialog__vram-base {
    color: var(--text-muted);
    margin-left: auto;
    font-size: var(--text-xs);
}

.model-load-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
}

/* Reuse mm-btn styles from ModelManager */
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
</style>
