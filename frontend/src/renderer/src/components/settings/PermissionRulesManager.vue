<script setup lang="ts">
/**
 * PermissionRulesManager — manage persistent permission rules (Fase 7).
 *
 * Persistent rules are the durable counterpart to the engine's ephemeral
 * session grants: a per-tool `allow` / `ask` / `deny` verdict the permission
 * gate consults on every call (precedence `deny` > `ask` > `allow`). A rule is
 * either *global* (applies to every conversation) or tied to the current
 * conversation.
 *
 * The list/add/delete go through `GET/POST/DELETE
 * /api/permission-rules/{conversation_id}`. The endpoints require a
 * conversation id in the path even for global rules, so when no conversation is
 * active the panel shows a hint instead.
 *
 * Like every permission surface, these are reachable only from the user — never
 * from a tool — which is why they live in Settings, not in the tool registry.
 */
import { computed, onMounted, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import UiSelect, { type UiSelectOption } from '../ui/UiSelect.vue'
import UiInput from '../ui/UiInput.vue'
import UiButton from '../ui/UiButton.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import { permissionsApi } from '../../services/api'
import { useChatStore } from '../../stores/chat'
import type { PermissionRule, RuleEffect, RuleScope } from '../../types/permission'

const chatStore = useChatStore()
const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

const rules = ref<PermissionRule[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)

/* Add-rule form state. */
const newTool = ref('')
const newEffect = ref<RuleEffect>('allow')
const newScope = ref<RuleScope>('global')

const effectOptions: UiSelectOption[] = [
  { value: 'allow', label: 'Consenti' },
  { value: 'ask', label: 'Chiedi' },
  { value: 'deny', label: 'Nega' }
]

const scopeOptions: UiSelectOption[] = [
  { value: 'global', label: 'Globale' },
  { value: 'conversation', label: 'Questa conversazione' }
]

const canSubmit = computed(
  () => !!conversationId.value && newTool.value.trim().length > 0 && !busy.value
)

/** Rules sorted deny → ask → allow, then by tool name, for a stable read. */
const sortedRules = computed<PermissionRule[]>(() => {
  const rank: Record<RuleEffect, number> = { deny: 0, ask: 1, allow: 2 }
  return [...rules.value].sort(
    (a, b) => rank[a.effect] - rank[b.effect] || a.tool_name.localeCompare(b.tool_name)
  )
})

async function load(id: string | null): Promise<void> {
  if (!id) {
    rules.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    rules.value = await permissionsApi.listPermissionRules(id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Errore nel caricamento delle regole'
  } finally {
    loading.value = false
  }
}

async function addRule(): Promise<void> {
  const id = conversationId.value
  const tool = newTool.value.trim()
  if (!id || !tool || busy.value) return
  busy.value = true
  error.value = null
  try {
    const created = await permissionsApi.addPermissionRule(id, {
      tool_name: tool,
      effect: newEffect.value,
      scope: newScope.value
    })
    // UPSERT: replace a matching (scope, tool) rule if present, else append.
    const idx = rules.value.findIndex((r) => r.id === created.id)
    if (idx >= 0) rules.value[idx] = created
    else rules.value.push(created)
    newTool.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Errore nell'aggiunta della regola"
  } finally {
    busy.value = false
  }
}

async function removeRule(rule: PermissionRule): Promise<void> {
  const id = conversationId.value
  if (!id || busy.value) return
  busy.value = true
  error.value = null
  try {
    await permissionsApi.deletePermissionRule(id, rule.id)
    rules.value = rules.value.filter((r) => r.id !== rule.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Errore nella rimozione della regola'
  } finally {
    busy.value = false
  }
}

onMounted(() => load(conversationId.value))
watch(conversationId, (id) => load(id))
</script>

<template>
  <div class="prm">
    <div class="prm__head">
      <span class="prm__title">Regole permanenti</span>
      <span class="prm__hint">
        Verdetti per-strumento sempre validi (precedenza: nega &gt; chiedi &gt; consenti).
      </span>
    </div>

    <UiEmptyState
      v-if="conversationId === null"
      title="Apri una conversazione per gestire le regole."
      icon="shield"
      compact
    />

    <template v-else>
      <!-- Add form -->
      <form class="prm__add" @submit.prevent="addRule">
        <UiInput
          v-model="newTool"
          type="text"
          size="sm"
          class="prm__input"
          placeholder="Nome strumento (es. run_terminal_command)"
          aria-label="Nome strumento"
        />
        <UiSelect
          class="prm__select"
          :model-value="newEffect"
          :options="effectOptions"
          size="sm"
          aria-label="Effetto"
          @update:model-value="(v) => (newEffect = v as RuleEffect)"
        />
        <UiSelect
          class="prm__select"
          :model-value="newScope"
          :options="scopeOptions"
          size="sm"
          aria-label="Ambito"
          @update:model-value="(v) => (newScope = v as RuleScope)"
        />
        <UiButton type="submit" variant="secondary" size="sm" :disabled="!canSubmit">
          <template #icon>
            <AppIcon name="plus" :size="14" :stroke-width="2" />
          </template>
          Aggiungi
        </UiButton>
      </form>

      <p v-if="error" class="prm__error">
        <AppIcon name="alert-triangle" :size="14" :stroke-width="2" />
        {{ error }}
      </p>

      <!-- List -->
      <p v-if="loading" class="prm__empty">Caricamento…</p>
      <UiEmptyState
        v-else-if="sortedRules.length === 0"
        title="Nessuna regola permanente."
        icon="inbox"
        compact
      />
      <ul v-else class="prm__list">
        <li v-for="rule in sortedRules" :key="rule.id" class="prm__item">
          <span class="prm__effect" :class="`prm__effect--${rule.effect}`">{{ rule.effect }}</span>
          <span class="prm__tool" :title="rule.tool_name">{{ rule.tool_name }}</span>
          <span class="prm__scope">{{ rule.conversation_id ? 'conversazione' : 'globale' }}</span>
          <UiIconButton
            label="Rimuovi regola"
            variant="ghost"
            size="xs"
            tone="danger"
            :disabled="busy"
            @click="removeRule(rule)"
          >
            <AppIcon name="trash" :size="14" :stroke-width="2" />
          </UiIconButton>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.prm {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.prm__head {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
}

.prm__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}

.prm__hint {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.prm__add {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
}

.prm__input {
  flex: 1 1 220px;
  min-width: 180px;
}

.prm__input :deep(.ui-input__field) {
  font-family: var(--font-mono);
}

.prm__select {
  min-width: 130px;
}

.prm__error {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  margin: 0;
  font-size: var(--text-xs);
  color: var(--error);
}

.prm__empty {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.prm__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.prm__item {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  padding: var(--space-2) var(--space-2-5);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.prm__effect {
  flex: 0 0 auto;
  min-width: 4.5ch;
  text-align: center;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: var(--space-0-5) var(--space-1-5);
  border-radius: var(--radius-sm);
}

.prm__effect--allow {
  color: var(--success, var(--accent));
  background: var(--success-bg, var(--surface-3));
}

.prm__effect--ask {
  color: var(--warning);
  background: var(--warning-bg);
}

.prm__effect--deny {
  color: var(--error);
  background: var(--error-bg);
}

.prm__tool {
  flex: 1 1 auto;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prm__scope {
  flex: 0 0 auto;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
</style>
