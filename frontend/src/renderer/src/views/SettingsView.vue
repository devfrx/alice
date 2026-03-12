<template>
  <div class="sv">
    <!-- Sidebar navigation -->
    <nav class="sv__nav">
      <div class="sv__nav-header">
        <h2 class="sv__title">Impostazioni</h2>
      </div>
      <ul class="sv__nav-list">
        <li v-for="item in navItems" :key="item.id">
          <button class="sv__nav-item" :class="{ 'sv__nav-item--active': activeSection === item.id }"
            @click="scrollTo(item.id)">
            <svg class="sv__nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" v-html="item.icon" />
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
            <button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.systemPromptEnabled }" role="switch"
              :aria-checked="settingsStore.systemPromptEnabled"
              @click="settingsStore.systemPromptEnabled = !settingsStore.systemPromptEnabled">
              <span class="sv__toggle-thumb" />
            </button>
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.systemPromptEnabled" class="sv__warn">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>Senza system prompt il modello non avrà istruzioni su personalità, limiti e strumenti.</span>
            </div>
          </Transition>

          <div class="sv__divider" />

          <div class="sv__row">
            <div class="sv__row-text">
              <span class="sv__row-label">Strumenti (Tool Calling)</span>
              <span class="sv__row-hint">Invia le definizioni degli strumenti al modello LLM</span>
            </div>
            <button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.toolsEnabled }" role="switch"
              :aria-checked="settingsStore.toolsEnabled"
              @click="settingsStore.toolsEnabled = !settingsStore.toolsEnabled">
              <span class="sv__toggle-thumb" />
            </button>
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.toolsEnabled" class="sv__warn">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>Senza tool calling il modello non potrà eseguire azioni (meteo, calendario, automazione).</span>
            </div>
          </Transition>
        </div>

        <div class="sv__fields">
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

      <!-- Voice -->
      <section :ref="(el) => setSectionRef('voice', el)" id="section-voice" class="sv__section">
        <VoiceSettings />
      </section>

      <!-- Plugins -->
      <section :ref="(el) => setSectionRef('plugins', el)" id="section-plugins" class="sv__section">
        <PluginManagement />
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
            <button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.toolConfirmations }" role="switch"
              :aria-checked="settingsStore.toolConfirmations"
              @click="settingsStore.toolConfirmations = !settingsStore.toolConfirmations">
              <span class="sv__toggle-thumb" />
            </button>
          </div>
          <Transition name="sv-warn">
            <div v-if="!settingsStore.toolConfirmations" class="sv__warn">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>Disabilitare le conferme riduce la sicurezza. Gli strumenti pericolosi verranno eseguiti senza
                approvazione.</span>
            </div>
          </Transition>
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
              <select v-model="settingsStore.settings.ui.theme" class="sv__input">
                <option value="dark">Scuro</option>
                <option value="light">Chiaro</option>
              </select>
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
import VoiceSettings from '../components/voice/VoiceSettings.vue'
import PluginManagement from '../components/settings/PluginManagement.vue'
import McpManager from '../components/settings/McpManager.vue'
import KnowledgeGraphManager from '../components/settings/KnowledgeGraphManager.vue'
import MemoryManager from '../components/settings/MemoryManager.vue'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()

/* ── Navigation ─────────────────────────────────────────────── */
type SectionId = 'model' | 'llm' | 'voice' | 'plugins' | 'mcp' | 'knowledge' | 'memory' | 'security' | 'ui'

const navItems: { id: SectionId; label: string; icon: string }[] = [
  { id: 'model', label: 'Modello', icon: '<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>' },
  { id: 'llm', label: 'Parametri LLM', icon: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>' },
  { id: 'voice', label: 'Voce', icon: '<path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>' },
  { id: 'plugins', label: 'Plugin', icon: '<rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>' },
  { id: 'mcp', label: 'Server MCP', icon: '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>' },
  { id: 'knowledge', label: 'Knowledge Graph', icon: '<circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/><line x1="5" y1="19" x2="19" y2="19"/>' },
  { id: 'memory', label: 'Memoria', icon: '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>' },
  { id: 'security', label: 'Sicurezza', icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>' },
  { id: 'ui', label: 'Interfaccia', icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>' },
]

const activeSection = ref<SectionId>('model')
const contentRef = ref<HTMLElement | null>(null)
const sectionRefs = reactive<Record<SectionId, HTMLElement | null>>({
  model: null, llm: null, voice: null, plugins: null, mcp: null, knowledge: null, memory: null, security: null, ui: null,
})

function setSectionRef(id: SectionId, el: Element | ComponentPublicInstance | null) {
  sectionRefs[id] = el as HTMLElement | null
}

function scrollTo(id: SectionId) {
  const el = sectionRefs[id]
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ── Track active section via IntersectionObserver ──────────── */
let observer: IntersectionObserver | null = null

function onScroll() {
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
  display: grid;
  grid-template-columns: 200px 1fr;
  height: 100%;
  color: var(--text-primary);
  overflow: hidden;
}

/* ── Sidebar navigation ──────────────────────────────────── */
.sv__nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-6) var(--space-3);
  border-right: 1px solid var(--border);
  background: var(--bg-primary);
  overflow-y: auto;
  position: sticky;
  top: 0;
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
  overflow-y: auto;
  padding: var(--space-6) var(--space-8);
  scroll-behavior: smooth;
  background: var(--bg-primary);
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
  max-width: 640px;
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

/* ── Toggle switch ────────────────────────────────────────── */
.sv__toggle {
  position: relative;
  width: 36px;
  height: 20px;
  border-radius: var(--radius-pill);
  border: none;
  background: var(--surface-3);
  cursor: pointer;
  transition: background var(--duration-fast) ease;
  flex-shrink: 0;
  padding: 0;
}

.sv__toggle--on {
  background: var(--accent);
}

.sv__toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-primary);
  transition:
    transform var(--duration-fast) ease,
    background var(--duration-fast) ease;
}

.sv__toggle--on .sv__toggle-thumb {
  transform: translateX(16px);
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
select.sv__input {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.4)' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 32px;
}

/* ── Bottom spacer ────────────────────────────────────────── */
.sv__spacer {
  height: 40vh;
}

/* ── Reduced motion ───────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {

  .sv__nav-item,
  .sv__nav-icon,
  .sv__toggle,
  .sv__toggle-thumb,
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
