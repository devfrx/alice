<script setup lang="ts">
/**
 * ChatToolControls.vue — In-chat agent-mode toggle + tool selector.
 *
 * Two compact chips meant to live in the input-bar toolbar:
 *
 *  1. Agent chip — toggles the *global* agent loop (drives
 *     `config.agent.enabled` through the settings store, so it is a
 *     true shortcut to the backend configuration).
 *
 *  2. Tools chip — opens a popover to pick which plugins / individual
 *     tools are offered to the LLM. The selection is persisted and
 *     sticky until changed. It is gated off when tools are globally
 *     disabled or when Tool RAG is active (auto-selection), since
 *     manual choice would have no effect in those cases.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import AppIcon from '../ui/AppIcon.vue'

const settingsStore = useSettingsStore()

const isOpen = ref(false)
const rootRef = ref<HTMLElement | null>(null)
/** Plugin names whose tool list is expanded in the popover. */
const expanded = ref<Set<string>>(new Set())

/** Whether the agent loop is currently active (global config). */
const agentEnabled = computed(() => settingsStore.settings.agent.enabled)

/** Whether manual tool selection has any effect right now. */
const available = computed(() => settingsStore.toolSelectionAvailable)

/** Reason the tool picker is disabled, for the tooltip. */
const disabledReason = computed(() => {
  if (!settingsStore.toolsEnabled) return 'Gli strumenti sono disattivati'
  if (settingsStore.settings.llm.toolRagEnabled)
    return 'Tool RAG attivo: gli strumenti sono selezionati automaticamente'
  return ''
})

const disabledCount = computed(() => settingsStore.disabledToolCount)

/** Toggle the global agent loop. */
function toggleAgent(): void {
  settingsStore.settings.agent.enabled = !settingsStore.settings.agent.enabled
}

function toggleOpen(): void {
  if (!available.value) return
  isOpen.value = !isOpen.value
}

function toggleExpand(plugin: string): void {
  const next = new Set(expanded.value)
  if (next.has(plugin)) next.delete(plugin)
  else next.add(plugin)
  expanded.value = next
}

/** Whether every tool of a plugin is currently enabled. */
function isPluginEnabled(plugin: string): boolean {
  const group = settingsStore.toolCatalog.find((p) => p.plugin === plugin)
  if (!group) return true
  return group.tools.every((t) => settingsStore.isToolEnabled(t.name))
}

function handleClickOutside(event: MouseEvent): void {
  if (rootRef.value && !rootRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') isOpen.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div ref="rootRef" class="ctc">
    <!-- Agent loop chip (drives global config) -->
    <button class="ctc__chip" :class="{ 'ctc__chip--on': agentEnabled }" role="switch"
      :aria-checked="agentEnabled" title="Attiva/disattiva la modalità agente (loop)" @click="toggleAgent">
      <AppIcon name="cpu" :size="11" />
      <span>{{ agentEnabled ? 'Agente' : 'Chat' }}</span>
    </button>

    <!-- Tool selector chip -->
    <button class="ctc__chip" :class="{ 'ctc__chip--open': isOpen, 'ctc__chip--muted': !available }"
      :disabled="!available" :title="available ? 'Seleziona gli strumenti attivi' : disabledReason"
      aria-haspopup="true" :aria-expanded="isOpen" @click="toggleOpen">
      <AppIcon name="sliders" :size="11" />
      <span>Strumenti</span>
      <span v-if="available && disabledCount > 0" class="ctc__badge">-{{ disabledCount }}</span>
    </button>

    <!-- Popover -->
    <Transition name="ctc-pop">
      <div v-if="isOpen" class="ctc__pop">
        <div class="ctc__pop-head">
          <span class="ctc__pop-title">Strumenti attivi</span>
          <button v-if="disabledCount > 0" class="ctc__reset" @click="settingsStore.resetToolSelection()">
            Ripristina tutti
          </button>
        </div>

        <div v-if="settingsStore.toolCatalog.length === 0" class="ctc__empty">
          Nessuno strumento disponibile.
        </div>

        <ul v-else class="ctc__list">
          <li v-for="group in settingsStore.toolCatalog" :key="group.plugin" class="ctc__group">
            <div class="ctc__group-head">
              <button class="ctc__expand" :aria-label="expanded.has(group.plugin) ? 'Comprimi' : 'Espandi'"
                @click="toggleExpand(group.plugin)">
                <AppIcon :name="expanded.has(group.plugin) ? 'chevron-down' : 'chevron-right'" :size="12" />
              </button>
              <span class="ctc__plugin-name">{{ group.plugin }}</span>
              <span class="ctc__plugin-count">{{ group.tools.length }}</span>
              <button class="ctc__sw" :class="{ 'ctc__sw--on': isPluginEnabled(group.plugin) }" role="switch"
                :aria-checked="isPluginEnabled(group.plugin)"
                @click="settingsStore.setPluginEnabled(group.plugin, !isPluginEnabled(group.plugin))">
                <span class="ctc__sw-thumb" />
              </button>
            </div>

            <ul v-if="expanded.has(group.plugin)" class="ctc__tools">
              <li v-for="tool in group.tools" :key="tool.name" class="ctc__tool">
                <div class="ctc__tool-text">
                  <span class="ctc__tool-name">{{ tool.label }}</span>
                  <span class="ctc__tool-desc">{{ tool.description }}</span>
                </div>
                <button class="ctc__sw" :class="{ 'ctc__sw--on': settingsStore.isToolEnabled(tool.name) }"
                  role="switch" :aria-checked="settingsStore.isToolEnabled(tool.name)"
                  @click="settingsStore.setToolEnabled(tool.name, !settingsStore.isToolEnabled(tool.name))">
                  <span class="ctc__sw-thumb" />
                </button>
              </li>
            </ul>
          </li>
        </ul>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.ctc {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ctc__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1));
  border-radius: 999px;
  background: var(--surface-2, rgba(255, 255, 255, 0.04));
  color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.ctc__chip:hover:not(:disabled) {
  background: var(--surface-3, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #fff);
}

.ctc__chip--on {
  background: var(--accent-soft, rgba(99, 102, 241, 0.18));
  border-color: var(--accent, #6366f1);
  color: var(--accent, #818cf8);
}

.ctc__chip--open {
  border-color: var(--accent, #6366f1);
  color: var(--text-primary, #fff);
}

.ctc__chip--muted,
.ctc__chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ctc__badge {
  padding: 0 5px;
  border-radius: 999px;
  background: var(--accent, #6366f1);
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  line-height: 14px;
}

.ctc__pop {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: 320px;
  max-height: 360px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1));
  border-radius: 12px;
  background: var(--surface-1, #1a1a1f);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  z-index: 50;
}

.ctc__pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 4px 8px;
}

.ctc__pop-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.ctc__reset {
  border: none;
  background: none;
  color: var(--accent, #818cf8);
  font-size: 11px;
  cursor: pointer;
}

.ctc__reset:hover {
  text-decoration: underline;
}

.ctc__empty {
  padding: 12px 4px;
  font-size: 12px;
  color: var(--text-secondary, rgba(255, 255, 255, 0.6));
  text-align: center;
}

.ctc__list,
.ctc__tools {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ctc__group {
  border-top: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}

.ctc__group:first-child {
  border-top: none;
}

.ctc__group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 4px;
}

.ctc__expand {
  display: inline-flex;
  border: none;
  background: none;
  color: var(--text-secondary, rgba(255, 255, 255, 0.6));
  cursor: pointer;
  padding: 2px;
}

.ctc__plugin-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary, #fff);
}

.ctc__plugin-count {
  font-size: 10px;
  color: var(--text-tertiary, rgba(255, 255, 255, 0.4));
}

.ctc__tools {
  padding: 0 4px 6px 26px;
}

.ctc__tool {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
}

.ctc__tool-text {
  flex: 1;
  min-width: 0;
}

.ctc__tool-name {
  display: block;
  font-size: 11px;
  color: var(--text-primary, #fff);
}

.ctc__tool-desc {
  display: block;
  font-size: 10px;
  color: var(--text-tertiary, rgba(255, 255, 255, 0.45));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ctc__sw {
  position: relative;
  flex-shrink: 0;
  width: 30px;
  height: 16px;
  border: none;
  border-radius: 999px;
  background: var(--surface-3, rgba(255, 255, 255, 0.14));
  cursor: pointer;
  transition: background 0.15s;
}

.ctc__sw--on {
  background: var(--accent, #6366f1);
}

.ctc__sw-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s;
}

.ctc__sw--on .ctc__sw-thumb {
  transform: translateX(14px);
}

.ctc-pop-enter-active,
.ctc-pop-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.ctc-pop-enter-from,
.ctc-pop-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
