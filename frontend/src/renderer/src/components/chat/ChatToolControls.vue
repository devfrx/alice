<script setup lang="ts">
/**
 * ChatToolControls.vue — In-chat tool reflection.
 *
 * Tools chip — opens a popover that is a READ-ONLY reflection of the active
 * permission tier. The tier (a per-conversation authorization mode) now governs
 * the offered toolset via a sovereign whitelist, so this control no longer edits
 * a manual selection — the editable global master switches live in Settings.
 *
 * Only the ``plan`` tier restricts: it withholds write/exec tools (except the
 * always-allowed planning tools). Every other tier offers everything. When Tool
 * RAG is on, tools are auto-selected per message *within* the tier's limits — we
 * surface a note but still render the full reflection.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useChatStore } from '../../stores/chat'
import { usePermissionModeStore } from '../../stores/permissionMode'
import type { PermissionMode } from '../../types/permission'
import AppIcon from '../ui/AppIcon.vue'
import UiPopover from '../ui/UiPopover.vue'
import { tierToolView, tierSummary } from './toolTierView'

const settingsStore = useSettingsStore()
const chatStore = useChatStore()
const permissionModeStore = usePermissionModeStore()

const isOpen = ref(false)
/** Trigger chip ("Strumenti") — anchor for the teleported popover. */
const triggerRef = ref<HTMLElement | null>(null)

/** Human-readable Italian label per tier (for the chip + blocked hint). */
const TIER_LABELS: Record<PermissionMode, string> = {
  strict: 'Rigorosa',
  auto_edits: 'Modifiche automatiche',
  plan: 'Pianificazione',
  autopilot: 'Autopilota',
}

/** The active conversation's permission tier (defaults to ``strict``). */
const activeTier = computed<PermissionMode>(() =>
  permissionModeStore.modeFor(chatStore.currentConversation?.id ?? ''),
)

/** Readable label of the active tier. */
const tierLabel = computed<string>(() => TIER_LABELS[activeTier.value] ?? activeTier.value)

/** One-line summary of what the active tier offers. */
const summary = computed<string>(() => tierSummary(activeTier.value))

/** The tool catalog projected through the active tier (allowed/planning flags). */
const groups = computed(() => tierToolView(activeTier.value, settingsStore.toolCatalog))

/** Whether Tool RAG auto-selects tools within the tier's limits. */
const ragActive = computed<boolean>(() => settingsStore.settings.llm.toolRagEnabled)

/** Number of tools withheld by the active tier (chip hint; non-zero only in plan). */
const blockedCount = computed<number>(() =>
  groups.value.reduce((n, g) => n + g.tools.filter((t) => !t.allowed).length, 0),
)

function toggleOpen(): void {
  isOpen.value = !isOpen.value
}

/** Fetch-once the permission tier for the active conversation. */
function ensureTier(id: string | undefined): void {
  if (id) void permissionModeStore.ensureForConversation(id)
}

onMounted(() => ensureTier(chatStore.currentConversation?.id))
watch(() => chatStore.currentConversation?.id, (id) => ensureTier(id))
</script>

<template>
  <div class="ctc">
    <!-- Tool reflection chip — always opens the read-only tier view -->
    <button
      ref="triggerRef"
      class="ctc__chip"
      :class="{ 'ctc__chip--open': isOpen }"
      :title="`Strumenti disponibili nella modalità ${tierLabel}`"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggleOpen"
    >
      <AppIcon name="sliders" :size="11" />
      <span class="ctc__chip-label">Strumenti</span>
      <span v-if="blockedCount > 0" class="ctc__badge" :title="`${blockedCount} strumenti bloccati dalla modalità`">
        <AppIcon name="minus" :size="9" />{{ blockedCount }}
      </span>
    </button>

    <!-- Popover — opens upward from the input bar, chrome from UiPopover -->
    <UiPopover
      :open="isOpen"
      :anchor-el="triggerRef"
      placement="top"
      align="start"
      width="320px"
      aria-label="Strumenti della modalità attiva"
      panel-class="ctc__pop"
      @update:open="isOpen = $event"
    >
      <div class="ctc__pop-head">
        <span class="ctc__pop-title">Strumenti</span>
        <span class="ctc__pop-tier">{{ tierLabel }}</span>
      </div>

      <p class="ctc__summary">{{ summary }}</p>

      <p v-if="ragActive" class="ctc__rag-note">
        <AppIcon name="auto-rotate" :size="11" />
        Selezione automatica (RAG) entro i limiti della modalità.
      </p>

      <div v-if="groups.length === 0" class="ctc__empty">
        Nessuno strumento disponibile.
      </div>

      <ul v-else class="ctc__list">
        <li v-for="group in groups" :key="group.plugin" class="ctc__group">
          <div class="ctc__group-head">
            <span class="ctc__plugin-name">{{ group.plugin }}</span>
            <span class="ctc__plugin-count">{{ group.tools.length }}</span>
          </div>

          <ul class="ctc__tools">
            <li
              v-for="tool in group.tools"
              :key="tool.name"
              class="ctc__tool"
              :class="{
                'ctc__tool--blocked': !tool.allowed,
                'ctc__tool--planning': tool.planning,
              }"
            >
              <span class="ctc__tool-state" aria-hidden="true">
                <AppIcon
                  :name="tool.allowed ? (tool.planning ? 'lightbulb' : 'check') : 'minus'"
                  :size="12"
                />
              </span>
              <div class="ctc__tool-text">
                <span class="ctc__tool-name">{{ tool.label }}</span>
                <span v-if="!tool.allowed" class="ctc__tool-hint">
                  bloccato dalla modalità {{ tierLabel }}
                </span>
                <span v-else-if="tool.planning" class="ctc__tool-hint ctc__tool-hint--ok">
                  pianificazione
                </span>
              </div>
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

/* Blocked-by-tier count badge (lock + count) */
.ctc__badge {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: var(--surface-4, var(--surface-3));
  color: var(--text-secondary);
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
  padding: var(--space-1) var(--space-1) var(--space-1);
}

.ctc__pop-title {
  font-family: var(--font-display);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

/* Active-tier pill in the header */
.ctc__pop-tier {
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--surface-3);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  font-weight: var(--weight-medium);
}

/* Tier summary line */
.ctc__summary {
  margin: 0;
  padding: 0 var(--space-1) var(--space-1-5);
  font-size: var(--text-2xs);
  line-height: 1.4;
  color: var(--text-secondary);
}

/* RAG auto-selection note */
.ctc__rag-note {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0 var(--space-1) var(--space-1-5);
  padding: var(--space-1) var(--space-1-5);
  border-radius: var(--radius-sm);
  background: var(--surface-3);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  line-height: 1.35;
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
  padding: var(--space-1-5) var(--space-1) var(--space-1);
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
  padding: 0 var(--space-1) var(--space-1-5);
}

/* Non-interactive tool row — read-only reflection of the tier */
.ctc__tool {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-1);
  border-radius: var(--radius-sm);
}

.ctc__tool-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  color: var(--success, var(--accent));
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

.ctc__tool-hint {
  display: block;
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.ctc__tool-hint--ok {
  color: var(--accent);
}

/* Planning tools — highlighted as in-evidence under the plan tier */
.ctc__tool--planning .ctc__tool-state {
  color: var(--accent);
}

/* Blocked tools — dimmed, lock state */
.ctc__tool--blocked {
  opacity: var(--opacity-disabled, 0.5);
}

.ctc__tool--blocked .ctc__tool-state {
  color: var(--text-muted);
}

.ctc__tool--blocked .ctc__tool-name {
  color: var(--text-secondary);
  text-decoration: line-through;
  text-decoration-color: var(--border);
}

</style>
