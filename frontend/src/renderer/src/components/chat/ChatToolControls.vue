<script setup lang="ts">
/**
 * ChatToolControls.vue — In-chat tool selector.
 *
 * Tools chip — opens a popover to pick which plugins / individual
 * tools are offered to the LLM. The selection is persisted and
 * sticky until changed. It is gated off when tools are globally
 * disabled or when Tool RAG is active (auto-selection), since
 * manual choice would have no effect in those cases.
 */
import { computed, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import AppIcon from '../ui/AppIcon.vue'
import UiPopover from '../ui/UiPopover.vue'

const settingsStore = useSettingsStore()

const isOpen = ref(false)
/** Trigger chip ("Strumenti") — anchor for the teleported popover. */
const triggerRef = ref<HTMLElement | null>(null)
/** Plugin names whose tool list is expanded in the popover. */
const expanded = ref<Set<string>>(new Set())

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
</script>

<template>
  <div class="ctc">
    <!-- Tool selector chip -->
    <button
      ref="triggerRef"
      class="ctc__chip"
      :class="{ 'ctc__chip--open': isOpen, 'ctc__chip--muted': !available }"
      :disabled="!available"
      :title="available ? 'Seleziona gli strumenti attivi' : disabledReason"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggleOpen"
    >
      <AppIcon name="sliders" :size="11" />
      <span class="ctc__chip-label">Strumenti</span>
      <span v-if="available && disabledCount > 0" class="ctc__badge">-{{ disabledCount }}</span>
    </button>

    <!-- Popover — opens upward from the input bar, chrome from UiPopover -->
    <UiPopover
      :open="isOpen"
      :anchor-el="triggerRef"
      placement="top"
      align="start"
      width="320px"
      aria-label="Strumenti attivi"
      panel-class="ctc__pop"
      @update:open="isOpen = $event"
    >
      <div class="ctc__pop-head">
        <span class="ctc__pop-title">Strumenti attivi</span>
        <button
          v-if="disabledCount > 0"
          class="ctc__reset"
          @click="settingsStore.resetToolSelection()"
        >
          Ripristina tutti
        </button>
      </div>

      <div v-if="settingsStore.toolCatalog.length === 0" class="ctc__empty">
        Nessuno strumento disponibile.
      </div>

      <ul v-else class="ctc__list">
        <li v-for="group in settingsStore.toolCatalog" :key="group.plugin" class="ctc__group">
          <div class="ctc__group-head">
            <button
              class="ctc__expand"
              :aria-label="expanded.has(group.plugin) ? 'Comprimi' : 'Espandi'"
              @click="toggleExpand(group.plugin)"
            >
              <AppIcon
                :name="expanded.has(group.plugin) ? 'chevron-down' : 'chevron-right'"
                :size="12"
              />
            </button>
            <span class="ctc__plugin-name">{{ group.plugin }}</span>
            <span class="ctc__plugin-count">{{ group.tools.length }}</span>
            <button
              class="ctc__sw"
              :class="{ 'ctc__sw--on': isPluginEnabled(group.plugin) }"
              role="switch"
              :aria-checked="isPluginEnabled(group.plugin)"
              @click="settingsStore.setPluginEnabled(group.plugin, !isPluginEnabled(group.plugin))"
            >
              <span class="ctc__sw-thumb" />
            </button>
          </div>

          <ul v-if="expanded.has(group.plugin)" class="ctc__tools">
            <li v-for="tool in group.tools" :key="tool.name" class="ctc__tool">
              <div class="ctc__tool-text">
                <span class="ctc__tool-name">{{ tool.label }}</span>
                <span class="ctc__tool-desc">{{ tool.description }}</span>
              </div>
              <button
                class="ctc__sw"
                :class="{ 'ctc__sw--on': settingsStore.isToolEnabled(tool.name) }"
                role="switch"
                :aria-checked="settingsStore.isToolEnabled(tool.name)"
                @click="
                  settingsStore.setToolEnabled(tool.name, !settingsStore.isToolEnabled(tool.name))
                "
              >
                <span class="ctc__sw-thumb" />
              </button>
            </li>
          </ul>
        </li>
      </ul>
    </UiPopover>
  </div>
</template>

<style scoped>
.ctc {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
}

/* ── Chip: shared spec for agent + tools buttons ── */
.ctc__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background var(--duration-fast) ease,
    color var(--duration-fast) ease,
    border-color var(--duration-fast) ease;
}

.ctc__chip:hover:not(:disabled) {
  background: var(--surface-3);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

/* Tools popover open */
.ctc__chip--open {
  border-color: var(--accent-border);
  background: var(--surface-3);
  color: var(--text-primary);
}

.ctc__chip--muted,
.ctc__chip:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.ctc__chip-label {
  display: inline;
}

/* Disabled count badge */
.ctc__badge {
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: var(--accent);
  color: var(--text-on-accent);
  font-size: 9px;
  font-weight: var(--weight-bold);
  line-height: 14px;
}
</style>

<!-- Popover content styles are NOT scoped (slot is teleported with UiPopover) -->
<style>
/* ── Popover content ── chrome (surface/border/radius/shadow/width) comes
   from UiPopover; only scroll constraints are owned here. */
.ctc__pop {
  max-height: 360px;
  overflow-y: auto;
}

.ctc__pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-1) var(--space-2);
}

.ctc__pop-title {
  font-family: var(--font-display);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.ctc__reset {
  border: none;
  background: none;
  color: var(--accent);
  font-size: var(--text-xs);
  cursor: pointer;
  padding: 0;
}

.ctc__reset:hover {
  text-decoration: underline;
}

.ctc__empty {
  padding: var(--space-3) var(--space-1);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  text-align: center;
}

.ctc__list,
.ctc__tools {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ctc__group {
  border-top: 1px solid var(--border);
}

.ctc__group:first-child {
  border-top: none;
}

.ctc__group-head {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1-5) var(--space-1);
}

.ctc__expand {
  display: inline-flex;
  border: none;
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px;
}

.ctc__plugin-name {
  flex: 1;
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}

.ctc__plugin-count {
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.ctc__tools {
  padding: 0 var(--space-1) var(--space-1-5) 26px;
}

.ctc__tool {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
}

.ctc__tool-text {
  flex: 1;
  min-width: 0;
}

.ctc__tool-name {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-primary);
}

.ctc__tool-desc {
  display: block;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Toggle switch ── */
.ctc__pop .ctc__sw {
  position: relative;
  flex-shrink: 0;
  width: 30px;
  height: 16px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--surface-3);
  cursor: pointer;
  transition: background var(--duration-fast) ease;
}

.ctc__pop .ctc__sw--on {
  background: var(--accent);
}

.ctc__pop .ctc__sw-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text-on-accent);
  transition: transform var(--duration-fast) ease;
}

.ctc__pop .ctc__sw--on .ctc__sw-thumb {
  transform: translateX(14px);
}
</style>
