<template>
  <div class="settings-view">
    <h2 class="settings-view__title">Impostazioni</h2>
    <div class="settings-view__content">
      <ModelManager />

      <!-- LLM Parameters -->
      <section class="settings-section">
        <h3 class="settings-section__title">Parametri LLM</h3>
        <div class="settings-section__grid">
          <label class="settings-field">
            <span class="settings-field__label">Temperatura</span>
            <input v-model.number="settingsStore.settings.llm.temperature" type="number" class="settings-field__input"
              min="0" max="2" step="0.1" />
          </label>
          <label class="settings-field">
            <span class="settings-field__label">Max Tokens</span>
            <input v-model.number="settingsStore.settings.llm.maxTokens" type="number" class="settings-field__input"
              min="256" max="131072" step="256" />
          </label>
          <label class="settings-field">
            <span class="settings-field__label">Max iterazioni strumenti</span>
            <input v-model.number="settingsStore.settings.llm.maxToolIterations" type="number"
              class="settings-field__input" min="1" max="100" step="1" />
          </label>
        </div>
      </section>

      <!-- Voice & STT/TTS Settings (unified) -->
      <VoiceSettings />

      <!-- Plugin Management -->
      <PluginManagement />

      <!-- Security Settings -->
      <section class="settings-section">
        <h3 class="settings-section__title">Sicurezza</h3>
        <div class="settings-section__grid">
          <label class="settings-field settings-field--toggle">
            <span class="settings-field__label">Conferme strumenti</span>
            <span class="settings-field__hint">Richiedi conferma prima di eseguire strumenti</span>
            <button class="settings-toggle" :class="{ 'settings-toggle--on': settingsStore.toolConfirmations }"
              role="switch" :aria-checked="settingsStore.toolConfirmations"
              @click="settingsStore.toolConfirmations = !settingsStore.toolConfirmations">
              <span class="settings-toggle__thumb" />
            </button>
          </label>
          <div v-if="!settingsStore.toolConfirmations" class="settings-warning">
            <span class="settings-warning__icon">⚠️</span>
            <span class="settings-warning__text">Disabilitare le conferme riduce la sicurezza. Gli strumenti pericolosi
              verranno eseguiti senza approvazione, sia da input testuale che vocale.</span>
          </div>
        </div>
      </section>

      <!-- UI Settings -->
      <section class="settings-section">
        <h3 class="settings-section__title">Interfaccia</h3>
        <div class="settings-section__grid">
          <label class="settings-field">
            <span class="settings-field__label">Tema</span>
            <select v-model="settingsStore.settings.ui.theme" class="settings-field__input">
              <option value="dark">Scuro</option>
              <option value="light">Chiaro</option>
            </select>
          </label>
          <label class="settings-field">
            <span class="settings-field__label">Lingua</span>
            <input v-model="settingsStore.settings.ui.language" type="text" class="settings-field__input" />
          </label>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import ModelManager from '../components/settings/ModelManager.vue'
import VoiceSettings from '../components/voice/VoiceSettings.vue'
import PluginManagement from '../components/settings/PluginManagement.vue'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()
</script>

<style scoped>
.settings-view {
  padding: var(--space-8);
  color: var(--text-primary);
  max-width: 900px;
  margin: 0 auto;
  height: 100%;
  overflow-y: auto;
}

.settings-view::-webkit-scrollbar {
  width: var(--space-1);
}

.settings-view::-webkit-scrollbar-track {
  background: transparent;
}

.settings-view::-webkit-scrollbar-thumb {
  background: var(--border-hover);
  border-radius: var(--space-0-5);
}

.settings-view::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

.settings-view__title {
  margin: 0 0 var(--space-6) 0;
  font-size: var(--text-xl);
}

.settings-view__content {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.settings-section {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  color: var(--text-primary);
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
  background: var(--bg-input, var(--bg-secondary));
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

.settings-field__hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  flex: 1;
}

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
  background: var(--accent-dim);
  border-color: var(--accent-border);
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

.settings-warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 170, 0, 0.08);
  border: 1px solid rgba(255, 170, 0, 0.25);
  border-radius: var(--radius-sm);
  grid-column: 1 / -1;
}

.settings-warning__icon {
  flex-shrink: 0;
  font-size: var(--text-sm);
}

.settings-warning__text {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.4;
}
</style>
