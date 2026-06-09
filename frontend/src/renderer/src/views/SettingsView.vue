<template>
  <div class="sv" aria-label="Impostazioni">
    <!-- Sidebar navigation -->
    <nav class="sv__nav" aria-label="Sezioni impostazioni">
      <div class="sv__nav-header">
        <h1 class="sv__title">Impostazioni</h1>
      </div>
      <ul class="sv__nav-list">
        <li v-for="item in navItems" :key="item.id">
          <button class="sv__nav-item" :class="{ 'sv__nav-item--active': activeSection === item.id }"
            @click="scrollTo(item.id)">
            <AppIcon :name="item.iconName" :size="16" :stroke-width="1.5" class="sv__nav-icon" />
            <span>{{ item.label }}</span>
          </button>
        </li>
      </ul>
    </nav>

    <!-- Scrollable content -->
    <div ref="contentRef" class="sv__content" @scroll="onScroll">
      <!-- Model -->
      <section :ref="(el) => setSectionRef('model', el)" id="section-model" class="sv__section">
        <ModelManager />
      </section>

      <!-- LLM Parameters -->
      <section :ref="(el) => setSectionRef('llm', el)" id="section-llm" class="sv__section">
        <div class="sv__section-head">
          <h3 class="sv__section-title">Parametri LLM</h3>
          <p class="sv__section-desc">Configura il comportamento del modello di linguaggio</p>
        </div>

        <div class="sv__group">
          <div class="sv__row">
            <div class="sv__row-text">
              <span class="sv__row-label">System Prompt</span>
              <span class="sv__row-hint">Invia il system prompt al modello LLM</span>
            </div>
            <UiToggle v-model="settingsStore.systemPromptEnabled" aria-label="System Prompt" />
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.systemPromptEnabled" class="sv__warn">
              <AppIcon name="alert-triangle" :size="14" :stroke-width="2" />
              <span>Senza system prompt il modello non avrà istruzioni su personalità, limiti e strumenti.</span>
            </div>
          </Transition>

          <div class="sv__divider" />

          <div class="sv__row">
            <div class="sv__row-text">
              <span class="sv__row-label">Strumenti (Tool Calling)</span>
              <span class="sv__row-hint">Invia le definizioni degli strumenti al modello LLM</span>
            </div>
            <UiToggle v-model="settingsStore.toolsEnabled" aria-label="Strumenti (Tool Calling)" />
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.toolsEnabled" class="sv__warn">
              <AppIcon name="alert-triangle" :size="14" :stroke-width="2" />
              <span>Senza tool calling il modello non potrà eseguire azioni (meteo, calendario, automazione).</span>
            </div>
          </Transition>
        </div>

        <div class="sv__fields">
          <label class="sv__field">
            <span class="sv__field-label">Come Alice deve chiamarti</span>
            <div class="sv__input-wrap">
              <input v-model="settingsStore.settings.llm.userPreferredName" type="text" class="sv__input"
                maxlength="80" placeholder="es. Marco" />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Temperatura</span>
            <div class="sv__input-wrap">
              <input v-model.number="settingsStore.settings.llm.temperature" type="number" class="sv__input" min="0"
                max="2" step="0.1" />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Max Tokens</span>
            <div class="sv__input-wrap">
              <input v-model.number="settingsStore.settings.llm.maxTokens" type="number" class="sv__input" min="256"
                max="131072" step="256" />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Max iterazioni strumenti</span>
            <div class="sv__input-wrap">
              <input v-model.number="settingsStore.settings.llm.maxToolIterations" type="number" class="sv__input"
                min="1" max="100" step="1" />
            </div>
          </label>
        </div>
      </section>

      <!-- Agent / Persona -->
      <section :ref="(el) => setSectionRef('persona', el)" id="section-persona" class="sv__section">
        <AgentPersonaSettings />
      </section>

      <!-- Voice -->
      <section :ref="(el) => setSectionRef('voice', el)" id="section-voice" class="sv__section">
        <VoiceSettings />
      </section>

      <!-- Plugins -->
      <section :ref="(el) => setSectionRef('plugins', el)" id="section-plugins" class="sv__section">
        <PluginManagement />
      </section>

      <!-- Email -->
      <section :ref="(el) => setSectionRef('email', el)" id="section-email" class="sv__section">
        <EmailSettings />
      </section>

      <!-- MCP Servers -->
      <section :ref="(el) => setSectionRef('mcp', el)" id="section-mcp" class="sv__section">
        <McpManager />
      </section>

      <!-- Knowledge Graph -->
      <section :ref="(el) => setSectionRef('knowledge', el)" id="section-knowledge" class="sv__section">
        <KnowledgeGraphManager />
      </section>

      <!-- Memory -->
      <section :ref="(el) => setSectionRef('memory', el)" id="section-memory" class="sv__section">
        <MemoryManager />
      </section>

      <!-- Vector Store -->
      <section :ref="(el) => setSectionRef('vectorstore', el)" id="section-vectorstore" class="sv__section">
        <VectorStoreManager />
      </section>

      <!-- Security -->
      <section :ref="(el) => setSectionRef('security', el)" id="section-security" class="sv__section">
        <div class="sv__section-head">
          <h3 class="sv__section-title">Sicurezza</h3>
          <p class="sv__section-desc">Controlla le autorizzazioni e i livelli di sicurezza</p>
        </div>
        <div class="sv__group">
          <div class="sv__row">
            <div class="sv__row-text">
              <span class="sv__row-label">Conferme strumenti</span>
              <span class="sv__row-hint">Richiedi conferma prima di eseguire strumenti</span>
            </div>
            <UiToggle v-model="settingsStore.toolConfirmations" aria-label="Conferma esecuzione strumenti" />
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.toolConfirmations" class="sv__warn">
              <AppIcon name="alert-triangle" :size="14" :stroke-width="2" />
              <span>Disabilitare le conferme riduce la sicurezza. Gli strumenti pericolosi verranno eseguiti senza
                approvazione.</span>
            </div>
          </Transition>
        </div>
        <div class="sv__group">
          <PermissionRulesManager />
        </div>
      </section>

      <!-- UI -->
      <section :ref="(el) => setSectionRef('ui', el)" id="section-ui" class="sv__section">
        <div class="sv__section-head">
          <h3 class="sv__section-title">Interfaccia</h3>
          <p class="sv__section-desc">Personalizza l'aspetto e la lingua dell'applicazione</p>
        </div>
        <div class="sv__fields">
          <label class="sv__field">
            <span class="sv__field-label">Tema</span>
            <div class="sv__input-wrap">
              <UiSelect class="sv__select" :model-value="settingsStore.settings.ui.theme" :options="themeOptions"
                size="md" aria-label="Tema"
                @update:model-value="(v) => (settingsStore.settings.ui.theme = v === 'light' ? 'light' : 'dark')" />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Lingua</span>
            <div class="sv__input-wrap">
              <input v-model="settingsStore.settings.ui.language" type="text" class="sv__input" />
            </div>
          </label>
        </div>
      </section>

      <!-- Bottom spacer for scroll tracking -->
      <div class="sv__spacer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ComponentPublicInstance } from 'vue'
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import ModelManager from '../components/settings/ModelManager.vue'
import AgentPersonaSettings from '../components/settings/AgentPersonaSettings.vue'
import EmailSettings from '../components/settings/EmailSettings.vue'
import VoiceSettings from '../components/voice/VoiceSettings.vue'
import PluginManagement from '../components/settings/PluginManagement.vue'
import McpManager from '../components/settings/McpManager.vue'
import KnowledgeGraphManager from '../components/settings/KnowledgeGraphManager.vue'
import MemoryManager from '../components/settings/MemoryManager.vue'
import VectorStoreManager from '../components/settings/VectorStoreManager.vue'
import PermissionRulesManager from '../components/settings/PermissionRulesManager.vue'
import AppIcon from '../components/ui/AppIcon.vue'
import UiSelect, { type UiSelectOption } from '../components/ui/UiSelect.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import type { AppIconName } from '../assets/icons'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()

/* ── UI theme select ────────────────────────────────────────── */
const themeOptions: UiSelectOption[] = [
  { value: 'dark', label: 'Scuro' },
  { value: 'light', label: 'Chiaro' },
]

/* ── Navigation ─────────────────────────────────────────────── */
type SectionId = 'model' | 'llm' | 'persona' | 'voice' | 'plugins' | 'email' | 'mcp' | 'knowledge' | 'memory' | 'vectorstore' | 'security' | 'ui'

const navItems: { id: SectionId; label: string; iconName: AppIconName }[] = [
  { id: 'model', label: 'Modello', iconName: 'package' },
  { id: 'llm', label: 'Parametri LLM', iconName: 'sliders' },
  { id: 'persona', label: 'Agente / Persona', iconName: 'user' },
  { id: 'voice', label: 'Voce', iconName: 'mic' },
  { id: 'plugins', label: 'Plugin', iconName: 'cpu' },
  { id: 'email', label: 'Email', iconName: 'mail' },
  { id: 'mcp', label: 'Server MCP', iconName: 'server' },
  { id: 'knowledge', label: 'Knowledge Graph', iconName: 'share-graph' },
  { id: 'memory', label: 'Memoria', iconName: 'book' },
  { id: 'vectorstore', label: 'Vector Store', iconName: 'database' },
  { id: 'security', label: 'Sicurezza', iconName: 'shield' },
  { id: 'ui', label: 'Interfaccia', iconName: 'settings' },
]

const activeSection = ref<SectionId>('model')
const contentRef = ref<HTMLElement | null>(null)
const sectionRefs = reactive<Record<SectionId, HTMLElement | null>>({
  model: null, llm: null, persona: null, voice: null, plugins: null, email: null, mcp: null, knowledge: null, memory: null, vectorstore: null, security: null, ui: null,
})

function setSectionRef(id: SectionId, el: Element | ComponentPublicInstance | null): void {
  sectionRefs[id] = el as HTMLElement | null
}

function scrollTo(id: SectionId): void {
  const el = sectionRefs[id]
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ── Track active section via IntersectionObserver ──────────── */
let observer: IntersectionObserver | null = null

function onScroll(): void {
  /* Fallback for browsers without IO — find topmost visible section */
  if (observer) return
  const container = contentRef.value
  if (!container) return
  const top = container.scrollTop
  let closest: SectionId = 'model'
  for (const item of navItems) {
    const el = sectionRefs[item.id]
    if (el && el.offsetTop <= top + 80) closest = item.id
  }
  activeSection.value = closest
}

onMounted(() => {
  const container = contentRef.value
  if (!container) return

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const id = entry.target.id.replace('section-', '') as SectionId
          activeSection.value = id
        }
      }
    },
    { root: container, rootMargin: '-20% 0px -70% 0px', threshold: 0 },
  )

  for (const item of navItems) {
    const el = sectionRefs[item.id]
    if (el) observer.observe(el)
  }
})

onUnmounted(() => {
  observer?.disconnect()
})
</script>

<style scoped>
/* ============================================================
   SettingsView — Supabase-inspired flat dashboard design
   ============================================================ */

/* ── Layout ───────────────────────────────────────────────── */
.sv {
  display: flex;
  height: calc(100% - 16px);
  margin: 8px;
  gap: 16px;
  color: var(--text-primary);
  overflow: hidden;
}

/* ── Sidebar navigation ──────────────────────────────────── */
.sv__nav {
  flex-shrink: 0;
  width: 180px;
  margin: 12px 0 12px 12px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-5) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow-y: auto;
}

.sv__nav::-webkit-scrollbar {
  width: 0;
}

.sv__nav-header {
  padding: 0 var(--space-2) var(--space-5);
}

.sv__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold, 600);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.sv__nav-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.sv__nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  cursor: pointer;
  transition:
    background var(--duration-fast) ease,
    color var(--duration-fast) ease;
}

.sv__nav-item:hover {
  background: var(--surface-hover);
  color: var(--text-secondary);
}

.sv__nav-item--active {
  background: var(--surface-selected);
  color: var(--text-primary);
}

.sv__nav-icon {
  flex-shrink: 0;
  opacity: 0.5;
  transition: opacity var(--duration-fast) ease;
}

.sv__nav-item:hover .sv__nav-icon {
  opacity: 0.7;
}

.sv__nav-item--active .sv__nav-icon {
  opacity: 1;
}

/* ── Content panel ────────────────────────────────────────── */
.sv__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6) var(--space-8);
  scroll-behavior: smooth;
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-sizing: border-box;
}

/* Ultra-thin scrollbar */
.sv__content::-webkit-scrollbar {
  width: 4px;
}

.sv__content::-webkit-scrollbar-track {
  background: transparent;
}

.sv__content::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: var(--radius-pill);
}

.sv__content::-webkit-scrollbar-thumb:hover {
  background: var(--surface-4);
}

/* ── Section ──────────────────────────────────────────────── */
.sv__section {
  width: 100%;
  margin-bottom: var(--space-8);
}

.sv__section-head {
  margin-bottom: var(--space-5);
}

.sv__section-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold, 600);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.sv__section-desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-muted);
  line-height: 1.5;
}

/* ── Group card (toggle rows) ────────────────────────────── */
.sv__group {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0 var(--space-4);
  margin-bottom: var(--space-4);
}

.sv__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) 0;
}

.sv__row-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sv__row-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium, 500);
  color: var(--text-primary);
}

.sv__row-hint {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: 1.4;
}

.sv__divider {
  height: 1px;
  background: var(--border);
}

/* ── Warning banner ───────────────────────────────────────── */
.sv__warn {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  margin: 0 0 var(--space-1) 0;
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-2xs);
  color: var(--text-secondary);
  line-height: 1.45;
}

.sv__warn svg {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--warning);
}

/* Warning transition */
.sv-warn-enter-active,
.sv-warn-leave-active {
  transition:
    opacity var(--duration-fast) ease,
    max-height var(--duration-fast) ease;
  overflow: hidden;
}

.sv-warn-enter-from,
.sv-warn-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
  margin-bottom: 0;
}

.sv-warn-enter-to,
.sv-warn-leave-from {
  opacity: 1;
  max-height: 80px;
}

/* ── Input fields ─────────────────────────────────────────── */
.sv__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-3);
}

.sv__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sv__field-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-medium, 500);
}

.sv__input-wrap {
  position: relative;
}

.sv__input {
  width: 100%;
  padding: 8px var(--space-3);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--duration-fast) ease;
  box-sizing: border-box;
}

.sv__input:focus {
  border-color: var(--border-hover);
}

.sv__input::placeholder {
  color: var(--text-muted);
}

/* Select dropdown */
.sv__select {
  width: 100%;
}

/* ── Bottom spacer ────────────────────────────────────────── */
.sv__spacer {
  height: 40vh;
}

/* ── Reduced motion ───────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {

  .sv__nav-item,
  .sv__nav-icon,
  .sv__input,
  .sv-warn-enter-active,
  .sv-warn-leave-active {
    transition: none;
  }

  .sv__content {
    scroll-behavior: auto;
  }
}
</style>
