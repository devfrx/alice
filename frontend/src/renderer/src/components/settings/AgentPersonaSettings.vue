<template>
  <UiSectionHeader
    class="sv__section-head"
    title="Agente / Persona"
    description="Personalizza il tono globale dell'assistente, le istruzioni per ciascun livello di autorizzazione e quali strumenti sono disponibili."
  />

  <!-- ── Global persona ───────────────────────────────────────── -->
  <div class="sv__fields sv__fields--stack">
    <label class="sv__field">
      <span class="sv__field-label">Persona globale</span>
      <UiTextarea
        v-model="persona"
        :rows="5"
        :maxlength="4000"
        placeholder="es. Rispondi sempre in modo conciso e diretto, in italiano."
        @blur="savePersona"
      />
      <span class="ap__hint"
        >Aggiunta in fondo al system prompt di base, in ogni conversazione.</span
      >
    </label>
  </div>

  <!-- ── Per-tier guidance ────────────────────────────────────── -->
  <div class="ap__subhead">
    <h4 class="ap__subtitle">Istruzioni per livello</h4>
    <p class="ap__subdesc">
      Testo specifico per ciascun livello di autorizzazione. Lascia vuoto per usare il testo
      predefinito del livello.
    </p>
  </div>

  <div class="sv__fields sv__fields--stack">
    <label v-for="tier in AGENT_TIERS" :key="tier.key" class="sv__field">
      <span class="sv__field-label ap__tier-label">
        <span>{{ tier.label }}</span>
        <UiButton
          v-if="tierGuidance[tier.key].trim()"
          variant="ghost"
          size="sm"
          @click="resetTier(tier.key)"
        >
          Ripristina predefinito
        </UiButton>
      </span>
      <UiTextarea
        v-model="tierGuidance[tier.key]"
        :rows="3"
        :maxlength="4000"
        placeholder="(usa il testo predefinito)"
        @blur="saveTier"
      />
      <span class="ap__hint">{{ tier.hint }}</span>
    </label>
  </div>

  <!-- ── Tool master switches ─────────────────────────────────── -->
  <div class="ap__subhead">
    <h4 class="ap__subtitle">Strumenti disponibili</h4>
    <p class="ap__subdesc">
      Interruttori globali on/off per ogni plugin e strumento. Sono indipendenti dal whitelist per
      livello: uno strumento disattivato qui non è mai offerto al modello.
    </p>
  </div>

  <div class="sv__group ap__tools">
    <div class="ap__tools-head">
      <span class="sv__row-label">{{ summary }}</span>
      <UiButton
        v-if="settingsStore.disabledToolCount > 0"
        variant="ghost"
        size="sm"
        @click="settingsStore.resetToolSelection()"
      >
        Riattiva tutti
      </UiButton>
    </div>

    <UiEmptyState
      v-if="settingsStore.toolCatalog.length === 0"
      title="Nessuno strumento disponibile."
      compact
    />

    <ul v-else class="ap__list">
      <li v-for="group in settingsStore.toolCatalog" :key="group.plugin" class="ap__group">
        <div class="ap__group-head">
          <UiIconButton
            :label="expanded.has(group.plugin) ? 'Comprimi' : 'Espandi'"
            variant="ghost"
            size="xs"
            toggle
            :active="expanded.has(group.plugin)"
            @click="toggleExpand(group.plugin)"
          >
            <AppIcon
              :name="expanded.has(group.plugin) ? 'chevron-down' : 'chevron-right'"
              :size="14"
            />
          </UiIconButton>
          <span class="ap__plugin">{{ group.plugin }}</span>
          <span class="ap__count">{{ group.tools.length }}</span>
          <UiToggle
            size="sm"
            :model-value="isPluginEnabled(group.plugin)"
            :aria-label="`Attiva ${group.plugin}`"
            @update:model-value="(v) => settingsStore.setPluginEnabled(group.plugin, v)"
          />
        </div>

        <ul v-if="expanded.has(group.plugin)" class="ap__tool-items">
          <li v-for="tool in group.tools" :key="tool.name" class="ap__tool">
            <div class="ap__tool-text">
              <span class="ap__tool-name">{{ tool.label }}</span>
              <span class="ap__tool-desc">{{ tool.description }}</span>
            </div>
            <UiToggle
              size="sm"
              :model-value="settingsStore.isToolEnabled(tool.name)"
              :aria-label="`Attiva ${tool.label}`"
              @update:model-value="(v) => settingsStore.setToolEnabled(tool.name, v)"
            />
          </li>
        </ul>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
/**
 * AgentPersonaSettings.vue — "Agente / Persona" settings section.
 *
 * Three editors over the backend `agent.prompts` config plus the global tool
 * master switches:
 *  1. Global persona textarea → `agent.prompts.persona` (appended to the base
 *     system prompt every turn).
 *  2. Four per-tier guidance textareas → `agent.prompts.tier_guidance[tier]`;
 *     a blank value lets the backend fall back to its built-in default text.
 *  3. The per-plugin / per-tool enable/disable list relocated here from the
 *     in-chat popover (reuses the settings store's tool-catalog actions).
 *
 * Persona / tier saves go through the layered-config endpoints via the store
 * (`PATCH /config`), and fire on blur. Tool switches persist immediately.
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { AGENT_TIERS } from '../../utils/agentPrompts'
import type { AgentTier } from '../../types/settings'
import AppIcon from '../ui/AppIcon.vue'
import UiToggle from '../ui/UiToggle.vue'
import UiTextarea from '../ui/UiTextarea.vue'
import UiSectionHeader from '../ui/UiSectionHeader.vue'
import UiButton from '../ui/UiButton.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'

const settingsStore = useSettingsStore()

/* ── Persona + tier guidance (two-way bound to the store) ───────── */
const persona = computed({
  get: () => settingsStore.agentPrompts.persona,
  set: (v: string) => {
    settingsStore.agentPrompts.persona = v
  }
})
const tierGuidance = computed(() => settingsStore.agentPrompts.tier_guidance)

function savePersona(): void {
  void settingsStore.saveAgentPersona()
}
function saveTier(): void {
  void settingsStore.saveAgentTierGuidance()
}
function resetTier(tier: AgentTier): void {
  void settingsStore.resetAgentTier(tier)
}

/* ── Tool master switches ───────────────────────────────────────── */
const expanded = ref<Set<string>>(new Set())

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

const summary = computed(() => {
  const off = settingsStore.disabledToolCount
  return off > 0 ? `${off} strumenti disattivati` : 'Tutti gli strumenti attivi'
})

onMounted(() => {
  void settingsStore.loadAgentPrompts()
})
</script>

<style src="../../assets/styles/settings-controls.css"></style>

<style scoped>
/* Stacked field layout (full-width textareas, one per row). */
.sv__fields--stack {
  grid-template-columns: 1fr;
}

.ap__hint {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: 1.4;
}

/* ── Sub-section headings ──────────────────────────────────────── */
.ap__subhead {
  margin: var(--space-2) 0 var(--space-3);
}

.ap__subtitle {
  margin: 0 0 2px;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold, 600);
  color: var(--text-primary);
}

.ap__subdesc {
  margin: 0;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: 1.45;
}

.ap__tier-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}

/* ── Tool master switches ──────────────────────────────────────── */
.ap__tools {
  padding: var(--space-2) var(--space-4) var(--space-3);
}

.ap__tools-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-1) 0 var(--space-2);
}

.ap__list,
.ap__tool-items {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ap__group {
  border-top: 1px solid var(--border);
}

.ap__group:first-child {
  border-top: none;
}

.ap__group-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}

.ap__plugin {
  flex: 1;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium, 500);
  color: var(--text-primary);
}

.ap__count {
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.ap__tool-items {
  padding: 0 0 var(--space-2) 28px;
}

.ap__tool {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) 0;
}

.ap__tool-text {
  flex: 1;
  min-width: 0;
}

.ap__tool-name {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-primary);
}

.ap__tool-desc {
  display: block;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
