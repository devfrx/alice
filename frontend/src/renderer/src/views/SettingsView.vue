<template>
  <div class="sv" aria-label="Impostazioni">
    <!-- Sidebar navigation -->
    <nav class="sv__nav" aria-label="Sezioni impostazioni">
      <div class="sv__nav-header">
        <h1 class="sv__title">Impostazioni</h1>
      </div>
      <ul class="sv__nav-list">
        <li v-for="item in navItems" :key="item.id">
          <button
            class="sv__nav-item"
            :class="{ 'sv__nav-item--active': activeSection === item.id }"
            @click="scrollTo(item.id)"
          >
            <AppIcon :name="item.iconName" :size="16" :stroke-width="1.5" class="sv__nav-icon" />
            <span>{{ item.label }}</span>
          </button>
        </li>
      </ul>
    </nav>

    <!-- Scrollable content -->
    <div ref="contentRef" class="sv__content" @scroll="onScroll">
      <!-- Model -->
      <section id="section-model" :ref="(el) => setSectionRef('model', el)" class="sv__section">
        <ModelManager />
      </section>

      <!-- Provider -->
      <section
        id="section-provider"
        :ref="(el) => setSectionRef('provider', el)"
        class="sv__section"
      >
        <OpenRouterManager />
      </section>

      <!-- LLM Parameters -->
      <section id="section-llm" :ref="(el) => setSectionRef('llm', el)" class="sv__section">
        <UiSectionHeader
          class="sv__section-head"
          title="Parametri LLM"
          description="Configura il comportamento del modello di linguaggio"
        />

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
              <span
                >Senza system prompt il modello non avrà istruzioni su personalità, limiti e
                strumenti.</span
              >
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
              <span
                >Senza tool calling il modello non potrà eseguire azioni (meteo, calendario,
                automazione).</span
              >
            </div>
          </Transition>
        </div>

        <div class="sv__fields">
          <UiInput
            v-model="settingsStore.settings.llm.userPreferredName"
            label="Come Alice deve chiamarti"
            type="text"
            :maxlength="80"
            placeholder="es. Marco"
          />
          <label class="sv__field">
            <span class="sv__field-label">Temperatura</span>
            <div class="sv__input-wrap">
              <input
                v-model.number="settingsStore.settings.llm.temperature"
                type="number"
                class="sv__input"
                min="0"
                max="2"
                step="0.1"
              />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Max Tokens</span>
            <div class="sv__input-wrap">
              <input
                v-model.number="settingsStore.settings.llm.maxTokens"
                type="number"
                class="sv__input"
                min="256"
                max="131072"
                step="256"
              />
            </div>
          </label>
          <label class="sv__field">
            <span class="sv__field-label">Max iterazioni strumenti</span>
            <div class="sv__input-wrap">
              <input
                v-model.number="settingsStore.settings.llm.maxToolIterations"
                type="number"
                class="sv__input"
                min="1"
                max="100"
                step="1"
              />
            </div>
          </label>
        </div>
      </section>

      <!-- Agent / Persona -->
      <section id="section-persona" :ref="(el) => setSectionRef('persona', el)" class="sv__section">
        <AgentPersonaSettings />
      </section>

      <!-- Voice -->
      <section id="section-voice" :ref="(el) => setSectionRef('voice', el)" class="sv__section">
        <VoiceSettings />
      </section>

      <!-- Plugins -->
      <section id="section-plugins" :ref="(el) => setSectionRef('plugins', el)" class="sv__section">
        <PluginManagement />
      </section>

      <!-- Email -->
      <section id="section-email" :ref="(el) => setSectionRef('email', el)" class="sv__section">
        <EmailSettings />
      </section>

      <!-- MCP Servers -->
      <section id="section-mcp" :ref="(el) => setSectionRef('mcp', el)" class="sv__section">
        <McpManager />
      </section>

      <!-- Knowledge Graph -->
      <section
        id="section-knowledge"
        :ref="(el) => setSectionRef('knowledge', el)"
        class="sv__section"
      >
        <KnowledgeGraphManager />
      </section>

      <!-- Memory -->
      <section id="section-memory" :ref="(el) => setSectionRef('memory', el)" class="sv__section">
        <MemoryManager />
      </section>

      <!-- Vector Store -->
      <section
        id="section-vectorstore"
        :ref="(el) => setSectionRef('vectorstore', el)"
        class="sv__section"
      >
        <VectorStoreManager />
      </section>

      <!-- Security -->
      <section
        id="section-security"
        :ref="(el) => setSectionRef('security', el)"
        class="sv__section"
      >
        <UiSectionHeader
          class="sv__section-head"
          title="Sicurezza"
          description="Controlla le autorizzazioni e i livelli di sicurezza"
        />
        <div class="sv__group">
          <div class="sv__row">
            <div class="sv__row-text">
              <span class="sv__row-label">Conferme strumenti</span>
              <span class="sv__row-hint">Richiedi conferma prima di eseguire strumenti</span>
            </div>
            <UiToggle
              v-model="settingsStore.toolConfirmations"
              aria-label="Conferma esecuzione strumenti"
            />
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.toolConfirmations" class="sv__warn">
              <AppIcon name="alert-triangle" :size="14" :stroke-width="2" />
              <span
                >Disabilitare le conferme riduce la sicurezza. Gli strumenti pericolosi verranno
                eseguiti senza approvazione.</span
              >
            </div>
          </Transition>
        </div>
        <div class="sv__group">
          <PermissionRulesManager />
        </div>
      </section>

      <!-- UI -->
      <section id="section-ui" :ref="(el) => setSectionRef('ui', el)" class="sv__section">
        <UiSectionHeader
          class="sv__section-head"
          title="Interfaccia"
          description="Personalizza l'aspetto e la lingua dell'applicazione"
        />
        <div class="sv__fields">
          <label class="sv__field">
            <span class="sv__field-label">Tema</span>
            <div class="sv__input-wrap">
              <UiSelect
                class="sv__select"
                :model-value="settingsStore.settings.ui.theme"
                :options="themeOptions"
                size="md"
                aria-label="Tema"
                @update:model-value="
                  (v) => (settingsStore.settings.ui.theme = v === 'light' ? 'light' : 'dark')
                "
              />
            </div>
          </label>
          <UiInput v-model="settingsStore.settings.ui.language" label="Lingua" type="text" />
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
import OpenRouterManager from '../components/settings/OpenRouterManager.vue'
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
import UiInput from '../components/ui/UiInput.vue'
import UiSectionHeader from '../components/ui/UiSectionHeader.vue'
import type { AppIconName } from '../assets/icons'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()

/* ── UI theme select ────────────────────────────────────────── */
const themeOptions: UiSelectOption[] = [
  { value: 'dark', label: 'Scuro' },
  { value: 'light', label: 'Chiaro' }
]

/* ── Navigation ─────────────────────────────────────────────── */
type SectionId =
  | 'model'
  | 'provider'
  | 'llm'
  | 'persona'
  | 'voice'
  | 'plugins'
  | 'email'
  | 'mcp'
  | 'knowledge'
  | 'memory'
  | 'vectorstore'
  | 'security'
  | 'ui'

const navItems: { id: SectionId; label: string; iconName: AppIconName }[] = [
  { id: 'model', label: 'Modello', iconName: 'package' },
  { id: 'provider', label: 'Provider', iconName: 'link' },
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
  { id: 'ui', label: 'Interfaccia', iconName: 'settings' }
]

const activeSection = ref<SectionId>('model')
const contentRef = ref<HTMLElement | null>(null)
const sectionRefs = reactive<Record<SectionId, HTMLElement | null>>({
  model: null,
  provider: null,
  llm: null,
  persona: null,
  voice: null,
  plugins: null,
  email: null,
  mcp: null,
  knowledge: null,
  memory: null,
  vectorstore: null,
  security: null,
  ui: null
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
    { root: container, rootMargin: '-20% 0px -70% 0px', threshold: 0 }
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
   SettingsView — house-style page frame.
   Follows the shared page recipe (cfr. EmailPageView / TerminalPageView):
   a --surface-0 wrapper padded by --space-2-5, holding bordered --surface-1
   panels (border, no shadow) so Settings reads like the rest of the app
   rather than as a standalone dashboard.
   ============================================================ */

/* ── Layout ───────────────────────────────────────────────── */
.sv {
  display: flex;
  width: 100%;
  height: 100%;
  padding: var(--space-2-5);
  gap: var(--space-2-5);
  background: var(--surface-0);
  color: var(--text-primary);
  overflow: hidden;
  box-sizing: border-box;
}

/* ── Sidebar navigation ──────────────────────────────────── */
.sv__nav {
  flex-shrink: 0;
  width: 180px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-5) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
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
  font-family: var(--font-display);
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
/* --surface-0 (identical to the old --bg-primary) keeps the exact backdrop the
   child managers were tuned against; the added border is what turns it into a
   framed panel (cfr. email-page__inbox). */
.sv__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6) var(--space-8);
  scroll-behavior: smooth;
  background: var(--surface-0);
  border: 1px solid var(--border);
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

/* ── Group card (toggle rows) ────────────────────────────── */
/* --surface-1 matches the card layer the child managers use, so inline groups
   and manager sections read as one set of cards on the surface-0 content.
   (Previously surface-0, i.e. the same colour as the bg — border-only.) */
.sv__group {
  background: var(--surface-1);
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

/* Matches UiInput's label so native fields and kit inputs read as one set. */
.sv__field-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: var(--weight-medium, 500);
}

.sv__input-wrap {
  position: relative;
}

/* Native number fields (temperature/max tokens/iterations): UiInput can't
   carry number typing + min/max/step, so they stay native — but they borrow
   UiInput's surface, hover and focus treatment to sit in the same visual set. */
.sv__input {
  width: 100%;
  height: var(--input-height-md);
  padding: 0 var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out-quart, ease);
  box-sizing: border-box;
}

.sv__input:hover {
  border-color: var(--border-hover);
}

.sv__input:focus {
  border-color: var(--accent-border);
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
