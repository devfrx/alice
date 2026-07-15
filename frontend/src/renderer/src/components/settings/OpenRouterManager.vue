<script setup lang="ts">
/**
 * OpenRouterManager.vue — Provider LLM section: local/cloud switcher, OpenRouter
 * API key, credits readout, and (stubbed for now) model catalog.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useOpenrouterStore } from '../../stores/openrouter'
import { useSettingsStore } from '../../stores/settings'
import type { LlmProvider } from '../../types/openrouter'
import UiButton from '../ui/UiButton.vue'
import UiInput from '../ui/UiInput.vue'
import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'
import OpenRouterCatalog from './OpenRouterCatalog.vue'

const settingsStore = useSettingsStore()
const openrouterStore = useOpenrouterStore()

const PROVIDER_OPTIONS: UiSegmentedOption[] = [
  { value: 'lmstudio', label: 'LM Studio', icon: 'cpu' },
  { value: 'ollama', label: 'Ollama', icon: 'chip' },
  { value: 'openrouter', label: 'OpenRouter', icon: 'link' }
]

const provider = computed<LlmProvider>({
  get: () => settingsStore.settings.llm.provider,
  set: (value) => {
    settingsStore.settings.llm.provider = value
  }
})

/** Draft value for the API key input — never prefilled with the real key. */
const apiKeyDraft = ref('')
const savingKey = ref(false)

const apiKeyPlaceholder = computed(() =>
  settingsStore.openrouterKeyConfigured
    ? 'API key configurata — incolla per sostituirla'
    : 'sk-or-...'
)

/** Save the draft API key, clear the field, and refresh credits. */
async function saveApiKey(): Promise<void> {
  const trimmed = apiKeyDraft.value.trim()
  if (!trimmed) return
  savingKey.value = true
  try {
    await settingsStore.setOpenrouterApiKey(trimmed)
    apiKeyDraft.value = ''
    await openrouterStore.loadCredits()
  } finally {
    savingKey.value = false
  }
}

/** "$X.XX residui" when the account reports a remaining limit, otherwise "$X.XX usati". */
const creditsText = computed(() => {
  const credits = openrouterStore.credits
  if (!credits) return null
  if (credits.limit_remaining != null) {
    return `$${credits.limit_remaining.toFixed(2)} residui`
  }
  return `$${(credits.usage ?? 0).toFixed(2)} usati`
})

/** Load the catalog, and credits when a key is already configured. */
function loadOpenRouterData(): void {
  openrouterStore.loadCatalog()
  if (settingsStore.openrouterKeyConfigured) {
    openrouterStore.loadCredits()
  }
}

watch(provider, (value) => {
  if (value === 'openrouter') loadOpenRouterData()
})

onMounted(() => {
  if (provider.value === 'openrouter') loadOpenRouterData()
})
</script>

<template>
  <section class="settings-section">
    <h3 class="settings-section__title">Provider LLM</h3>
    <p class="or-hint">
      LM Studio e Ollama girano in locale sul tuo hardware. OpenRouter è un provider cloud a
      consumo: richiede una API key e addebita in base all'uso.
    </p>

    <UiSegmented
      :model-value="provider"
      :options="PROVIDER_OPTIONS"
      :equal="false"
      aria-label="Provider LLM"
      @update:model-value="(v) => (provider = v as LlmProvider)"
    />

    <div v-if="provider === 'openrouter'" class="or-panel">
      <div class="or-key-row">
        <UiInput
          v-model="apiKeyDraft"
          type="password"
          label="API key OpenRouter"
          :placeholder="apiKeyPlaceholder"
          autocomplete="off"
          class="or-key-input"
        />
        <UiButton
          variant="primary"
          :disabled="!apiKeyDraft.trim()"
          :loading="savingKey"
          @click="saveApiKey"
        >
          Salva chiave
        </UiButton>
      </div>

      <div v-if="settingsStore.openrouterKeyConfigured" class="or-credits">
        <span v-if="creditsText" class="or-credits__amount">{{ creditsText }}</span>
        <span v-else class="or-credits__hint">Crediti non disponibili — verifica la chiave</span>
        <UiButton
          variant="ghost"
          size="sm"
          :loading="openrouterStore.loadingCredits"
          @click="openrouterStore.loadCredits()"
        >
          Aggiorna
        </UiButton>
      </div>

      <OpenRouterCatalog />
    </div>
  </section>
</template>

<style scoped>
.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.or-hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0 0 var(--space-3) 0;
  line-height: var(--leading-snug);
}

.or-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.or-key-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.or-key-input {
  flex: 1;
  min-width: 0;
}

.or-credits {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.or-credits__amount {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.or-credits__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
</style>
