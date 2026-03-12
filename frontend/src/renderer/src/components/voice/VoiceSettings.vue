<script setup lang="ts">
/**
 * VoiceSettings.vue — Unified voice, STT & TTS configuration panel.
 *
 * Single source of truth for all voice-related settings. Loads config
 * from backend on mount and persists changes via PUT /config.
 */
import { onMounted, ref } from 'vue'
import { api } from '../../services/api'
import { useSettingsStore } from '../../stores/settings'
import { useVoiceStore } from '../../stores/voice'

const settingsStore = useSettingsStore()
const voiceStore = useVoiceStore()

// Local state — overwritten once backend responds
const loaded = ref(false)
const saving = ref(false)
const saveError = ref('')

// STT
const sttEnabled = ref(true)
const sttModel = ref('small')
const sttLanguage = ref('it')

// TTS
const ttsEnabled = ref(true)
const ttsEngine = ref('piper')
const ttsVoice = ref(settingsStore.settings.tts.voice)
const ttsSpeed = ref(1.0)
const kokoroVoice = ref('if_sara')
const kokoroLanguage = ref('it')

// Voice
const activationMode = ref('push_to_talk')
const autoTtsResponse = ref(true)
const wakeWord = ref('omnia')

const sttModels = [
  { value: 'tiny', label: 'Tiny (veloce, meno preciso)' },
  { value: 'base', label: 'Base' },
  { value: 'small', label: 'Small (bilanciato)' },
  { value: 'medium', label: 'Medium' },
  { value: 'large-v3', label: 'Large v3 (preciso, lento)' },
]

const activationModes = [
  { value: 'push_to_talk', label: 'Premi per parlare' },
  { value: 'wake_word', label: 'Parola di attivazione' },
  { value: 'always_on', label: 'Sempre attivo' },
]

const ttsEnginesAll = [
  { value: 'piper', label: 'Piper (CPU, veloce)' },
  { value: 'kokoro', label: 'Kokoro (CPU/GPU, alta qualità)' },
  { value: 'xtts', label: 'XTTS v2 (GPU, clonazione voce)' },
]

/** Filtered to only the engines whose Python library is installed. */
const ttsEngines = ref(ttsEnginesAll)
/** False when faster-whisper is not installed. */
const sttLibAvailable = ref(true)

/** Kokoro voices grouped by language, with auto-language mapping. */
const kokoroVoices: { group: string; lang: string; voices: { value: string; label: string }[] }[] = [
  {
    group: '🇮🇹 Italiano', lang: 'it',
    voices: [
      { value: 'if_sara', label: 'Sara (femminile)' },
      { value: 'im_nicola', label: 'Nicola (maschile)' },
    ],
  },
  {
    group: '🇺🇸 English (US)', lang: 'en-us',
    voices: [
      { value: 'am_michael', label: 'Michael (maschile)' },
      { value: 'am_fenrir', label: 'Fenrir (maschile)' },
      { value: 'am_onyx', label: 'Onyx (maschile)' },
      { value: 'am_echo', label: 'Echo (maschile)' },
      { value: 'am_eric', label: 'Eric (maschile)' },
      { value: 'am_liam', label: 'Liam (maschile)' },
      { value: 'am_adam', label: 'Adam (maschile)' },
      { value: 'am_puck', label: 'Puck (maschile)' },
      { value: 'af_heart', label: 'Heart (femminile)' },
      { value: 'af_sarah', label: 'Sarah (femminile)' },
      { value: 'af_nova', label: 'Nova (femminile)' },
      { value: 'af_sky', label: 'Sky (femminile)' },
      { value: 'af_bella', label: 'Bella (femminile)' },
      { value: 'af_jessica', label: 'Jessica (femminile)' },
      { value: 'af_nicole', label: 'Nicole (femminile)' },
      { value: 'af_river', label: 'River (femminile)' },
    ],
  },
  {
    group: '🇬🇧 English (UK)', lang: 'en-gb',
    voices: [
      { value: 'bm_daniel', label: 'Daniel (maschile)' },
      { value: 'bm_george', label: 'George (maschile)' },
      { value: 'bm_lewis', label: 'Lewis (maschile)' },
      { value: 'bm_fable', label: 'Fable (maschile)' },
      { value: 'bf_emma', label: 'Emma (femminile)' },
      { value: 'bf_alice', label: 'Alice (femminile)' },
      { value: 'bf_isabella', label: 'Isabella (femminile)' },
      { value: 'bf_lily', label: 'Lily (femminile)' },
    ],
  },
  {
    group: '🇫🇷 Français', lang: 'fr-fr',
    voices: [
      { value: 'ff_siwis', label: 'Siwis (femminile)' },
    ],
  },
  {
    group: '🇪🇸 Español', lang: 'es',
    voices: [
      { value: 'ef_dora', label: 'Dora (femminile)' },
      { value: 'em_alex', label: 'Alex (maschile)' },
    ],
  },
  {
    group: '🇯🇵 日本語', lang: 'ja',
    voices: [
      { value: 'jf_alpha', label: 'Alpha (femminile)' },
      { value: 'jf_nezumi', label: 'Nezumi (femminile)' },
      { value: 'jm_kumo', label: 'Kumo (maschile)' },
    ],
  },
  {
    group: '🇨🇳 中文', lang: 'zh',
    voices: [
      { value: 'zf_xiaoxiao', label: 'Xiaoxiao (femminile)' },
      { value: 'zf_xiaoyi', label: 'Xiaoyi (femminile)' },
      { value: 'zm_yunxi', label: 'Yunxi (maschile)' },
      { value: 'zm_yunyang', label: 'Yunyang (maschile)' },
    ],
  },
]

/** Map voice → its canonical language code. */
const voiceLangMap = Object.fromEntries(
  kokoroVoices.flatMap(g => g.voices.map(v => [v.value, g.lang]))
)

function onKokoroVoiceChange(): void {
  const lang = voiceLangMap[kokoroVoice.value]
  if (lang) kokoroLanguage.value = lang
  save()
}

onMounted(async () => {
  try {
    const [cfg, engines] = await Promise.all([
      api.getConfig(),
      api.getAvailableVoiceEngines().catch(() => null),
    ])

    // Filter TTS engine list to only installed libraries.
    if (engines) {
      ttsEngines.value = ttsEnginesAll.filter((e) => engines.tts[e.value] === true)
      sttLibAvailable.value = engines.stt['faster_whisper'] === true
    }

    const stt = cfg.stt as Record<string, unknown> | undefined
    const tts = cfg.tts as Record<string, unknown> | undefined
    const voice = cfg.voice as Record<string, unknown> | undefined
    if (stt) {
      sttEnabled.value = (stt.enabled as boolean) ?? true
      sttModel.value = (stt.model as string) ?? 'small'
      sttLanguage.value = (stt.language as string) ?? 'it'
    }
    if (tts) {
      ttsEnabled.value = (tts.enabled as boolean) ?? true
      ttsEngine.value = (tts.engine as string) ?? 'piper'
      ttsVoice.value = (tts.voice as string) ?? ttsVoice.value
      ttsSpeed.value = (tts.speed as number) ?? 1.0
      kokoroVoice.value = (tts.kokoro_voice as string) ?? 'if_sara'
      kokoroLanguage.value = (tts.kokoro_language as string) ?? 'it'
    }
    if (voice) {
      activationMode.value = (voice.activation_mode as string) ?? 'push_to_talk'
      autoTtsResponse.value = (voice.auto_tts_response as boolean) ?? true
      wakeWord.value = (voice.wake_word as string) ?? 'omnia'
    }
  } catch (err) {
    console.warn('[VoiceSettings] Failed to load config:', err)
  }
  loaded.value = true
})

async function save(): Promise<void> {
  saving.value = true
  saveError.value = ''
  try {
    await api.updateConfig({
      stt: {
        enabled: sttEnabled.value,
        model: sttModel.value,
        language: sttLanguage.value,
      },
      tts: {
        engine: ttsEngine.value,
        voice: ttsVoice.value,
        speed: ttsSpeed.value,
        enabled: ttsEnabled.value,
        kokoro_voice: kokoroVoice.value,
        kokoro_language: kokoroLanguage.value,
      },
      voice: {
        auto_tts_response: autoTtsResponse.value,
        activation_mode: activationMode.value,
        wake_word: wakeWord.value,
      },
    })
    // Keep settings store in sync
    settingsStore.settings.tts.engine = ttsEngine.value
    settingsStore.settings.tts.voice = ttsVoice.value
    settingsStore.settings.stt.model = sttModel.value
    settingsStore.settings.stt.language = sttLanguage.value
    // Keep voice store in sync (used by useVoice composable)
    voiceStore.activationMode = activationMode.value as typeof voiceStore.activationMode
    voiceStore.wakeWord = wakeWord.value
    voiceStore.autoTtsResponse = autoTtsResponse.value
  } catch (err) {
    saveError.value = 'Salvataggio fallito'
    console.warn('[VoiceSettings] Failed to save config:', err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="vs" role="region" aria-label="Impostazioni voce e audio">
    <template v-if="loaded">
      <!-- STT Section -->
      <section class="settings-section" aria-labelledby="stt-heading">
        <h3 id="stt-heading" class="settings-section__title">Riconoscimento Vocale (STT)</h3>
        <div class="settings-section__grid">
          <p v-if="!sttLibAvailable" class="settings-unavailable-hint">
            ⚠ faster-whisper non installato — STT non disponibile.
            Installa con: <code>uv sync --extra voice --extra voice-gpu</code>

          </p>
          <label class="settings-field settings-field--toggle">
            <span class="settings-field__label">Abilita STT</span>
            <span class="settings-field__hint">Riconoscimento vocale tramite Whisper</span>
            <button class="settings-toggle" :class="{ 'settings-toggle--on': sttEnabled }" role="switch"
              :aria-checked="sttEnabled" :disabled="!sttLibAvailable" @click="sttEnabled = !sttEnabled; save()">
              <span class="settings-toggle__thumb" />
            </button>
          </label>
          <template v-if="sttEnabled && sttLibAvailable">
            <label class="settings-field">
              <span class="settings-field__label">Modello</span>
              <select v-model="sttModel" class="settings-field__input" aria-label="Modello STT" @change="save">
                <option v-for="m in sttModels" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </label>
            <label class="settings-field">
              <span class="settings-field__label">Lingua</span>
              <input v-model="sttLanguage" type="text" class="settings-field__input" placeholder="it"
                aria-label="Lingua STT" @change="save" />
            </label>
          </template>
        </div>
      </section>

      <!-- TTS Section -->
      <section class="settings-section" aria-labelledby="tts-heading">
        <h3 id="tts-heading" class="settings-section__title">Sintesi Vocale (TTS)</h3>
        <div class="settings-section__grid">
          <p v-if="ttsEngines.length === 0" class="settings-unavailable-hint">
            ⚠ Nessun motore TTS installato. Installa con:
            <code>uv sync --extra tts-piper</code>
          </p>
          <label class="settings-field settings-field--toggle">
            <span class="settings-field__label">Abilita TTS</span>
            <span class="settings-field__hint">Sintesi vocale delle risposte</span>
            <button class="settings-toggle" :class="{ 'settings-toggle--on': ttsEnabled }" role="switch"
              :aria-checked="ttsEnabled" :disabled="ttsEngines.length === 0" @click="ttsEnabled = !ttsEnabled; save()">
              <span class="settings-toggle__thumb" />
            </button>
          </label>
          <template v-if="ttsEnabled && ttsEngines.length > 0">
            <label class="settings-field">
              <span class="settings-field__label">Motore</span>
              <select v-model="ttsEngine" class="settings-field__input" aria-label="Motore TTS" @change="save">
                <option v-for="e in ttsEngines" :key="e.value" :value="e.value">{{ e.label }}</option>
              </select>
            </label>
            <label v-if="ttsEngine !== 'kokoro'" class="settings-field">
              <span class="settings-field__label">Voce</span>
              <input v-model="ttsVoice" type="text" class="settings-field__input"
                placeholder="models/tts/it_IT-paola-medium" aria-label="Percorso voce TTS" @change="save" />
            </label>
            <template v-if="ttsEngine === 'kokoro'">
              <label class="settings-field">
                <span class="settings-field__label">Voce Kokoro</span>
                <select v-model="kokoroVoice" class="settings-field__input" aria-label="Voce Kokoro"
                  @change="onKokoroVoiceChange">
                  <optgroup v-for="group in kokoroVoices" :key="group.group" :label="group.group">
                    <option v-for="v in group.voices" :key="v.value" :value="v.value">{{ v.label }}</option>
                  </optgroup>
                </select>
              </label>
              <label class="settings-field">
                <span class="settings-field__label">Lingua Kokoro</span>
                <select v-model="kokoroLanguage" class="settings-field__input" aria-label="Lingua Kokoro"
                  @change="save">
                  <option value="it">Italiano</option>
                  <option value="en-us">English (US)</option>
                  <option value="en-gb">English (UK)</option>
                  <option value="fr-fr">Français</option>
                  <option value="es">Español</option>
                  <option value="de">Deutsch</option>
                  <option value="ja">日本語</option>
                  <option value="zh">中文</option>
                </select>
              </label>
            </template>
            <label class="settings-field settings-field--wide">
              <span class="settings-field__label">Velocità</span>
              <div class="vs__range-row">
                <input v-model.number="ttsSpeed" type="range" min="0.5" max="2.0" step="0.1" class="vs__range"
                  aria-label="Velocità TTS" @change="save" />
                <span class="vs__range-value">{{ ttsSpeed.toFixed(1) }}x</span>
              </div>
            </label>
            <label class="settings-field settings-field--toggle">
              <span class="settings-field__label">Rispondi automaticamente a voce</span>
              <span class="settings-field__hint">L'assistente legge automaticamente le risposte</span>
              <button class="settings-toggle" :class="{ 'settings-toggle--on': autoTtsResponse }" role="switch"
                :aria-checked="autoTtsResponse" @click="autoTtsResponse = !autoTtsResponse; save()">
                <span class="settings-toggle__thumb" />
              </button>
            </label>
          </template>
        </div>
      </section>

      <!-- Voice Interaction -->
      <section class="settings-section" aria-labelledby="voice-heading">
        <h3 id="voice-heading" class="settings-section__title">Interazione Vocale</h3>
        <div class="settings-section__grid">
          <label class="settings-field settings-field--toggle">
            <span class="settings-field__label">Conferma invio trascrizione</span>
            <span class="settings-field__hint">Mostra Invia/Annulla dopo la trascrizione vocale</span>
            <button class="settings-toggle" :class="{ 'settings-toggle--on': voiceStore.confirmTranscript }"
              role="switch" :aria-checked="voiceStore.confirmTranscript"
              @click="voiceStore.confirmTranscript = !voiceStore.confirmTranscript">
              <span class="settings-toggle__thumb" />
            </button>
          </label>
          <label class="settings-field settings-field--toggle">
            <span class="settings-field__label">Includi allegati con invio vocale</span>
            <span class="settings-field__hint">Invia anche gli allegati presenti in chat</span>
            <button class="settings-toggle" :class="{ 'settings-toggle--on': voiceStore.sttIncludeAttachments }"
              role="switch" :aria-checked="voiceStore.sttIncludeAttachments"
              @click="voiceStore.sttIncludeAttachments = !voiceStore.sttIncludeAttachments">
              <span class="settings-toggle__thumb" />
            </button>
          </label>
        </div>
      </section>

      <!-- Activation Mode -->
      <section class="settings-section" aria-labelledby="activation-heading">
        <h3 id="activation-heading" class="settings-section__title">Modalità Attivazione</h3>
        <div class="vs__activation-grid">
          <label v-for="mode in activationModes" :key="mode.value" class="vs__activation-card"
            :class="{ 'vs__activation-card--active': activationMode === mode.value }">
            <input v-model="activationMode" type="radio" :value="mode.value" name="activation-mode"
              class="vs__activation-radio" @change="save" />
            <span class="vs__activation-label">{{ mode.label }}</span>
          </label>
        </div>
        <div v-if="activationMode === 'wake_word'" class="vs__wake-word-row">
          <label class="settings-field">
            <span class="settings-field__label">Parola di attivazione</span>
            <input v-model="wakeWord" type="text" class="settings-field__input" placeholder="omnia"
              aria-label="Parola di attivazione" @change="save" />
          </label>
        </div>
      </section>

      <!-- Save feedback -->
      <div v-if="saveError" class="vs__error">{{ saveError }}</div>
    </template>

    <div v-else class="vs__loading">Caricamento impostazioni voce...</div>
  </div>
</template>

<style scoped>
.vs {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.vs__range-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
}

.vs__range {
  flex: 1;
  accent-color: var(--accent);
}

.vs__range-value {
  min-width: 36px;
  text-align: right;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.vs__loading {
  font-size: var(--text-sm);
  color: var(--text-muted);
  padding: var(--space-2) 0;
}

.vs__activation-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}

.vs__activation-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-2);
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
  font-size: var(--text-sm);
}

.vs__activation-card:hover {
  border-color: var(--border-hover);
}

.vs__activation-card--active {
  border-color: var(--accent-border);
  background: var(--accent-dim);
}

.vs__activation-radio {
  accent-color: var(--accent);
}

.vs__activation-label {
  color: var(--text-primary);
}

.vs__wake-word-row {
  margin-top: var(--space-2);
}

.vs__error {
  font-size: var(--text-sm);
  color: var(--danger);
  padding: var(--space-1) var(--space-2);
}

/* ── Settings sections ── */
.settings-section {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  color: var(--text-primary);
}

.settings-unavailable-hint {
  grid-column: 1 / -1;
  margin: 0 0 var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--warning-bg);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.settings-unavailable-hint code {
  font-family: var(--font-mono);
  background: var(--surface-2);
  padding: 0 var(--space-1);
  border-radius: var(--radius-xs);
}

.settings-section__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-3);
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.settings-field__label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.settings-field__input {
  padding: 7px var(--space-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  outline: none;
  transition: border-color var(--transition-fast);
}

.settings-field__input:focus {
  border-color: var(--accent-border);
}

.settings-field--toggle {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  grid-column: 1 / -1;
}

.settings-field--wide {
  grid-column: 1 / -1;
}

.settings-field__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  flex: 1;
}

.settings-toggle {
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
  flex-shrink: 0;
  padding: 0;
}

.settings-toggle--on {
  background: var(--accent-dim);
  border-color: var(--accent-border);
}

.settings-toggle__thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--text-muted);
  transition: transform var(--transition-fast), background var(--transition-fast);
}

.settings-toggle--on .settings-toggle__thumb {
  transform: translateX(18px);
  background: var(--accent);
}
</style>
