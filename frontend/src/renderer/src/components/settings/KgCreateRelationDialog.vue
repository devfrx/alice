<script setup lang="ts">
/**
 * KgCreateRelationDialog — Form for creating a new Knowledge Graph relation.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (created) or `false` (cancelled).
 */
import { reactive } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'
import UiSelect, { type UiSelectOption } from '../ui/UiSelect.vue'
import UiButton from '../ui/UiButton.vue'
import UiInput from '../ui/UiInput.vue'

const props = defineProps<{
  entities: UiSelectOption[]
}>()

const emit = defineEmits<{ close: [result: boolean] }>()

const store = useMcpMemoryStore()

const form = reactive({ from: '', to: '', relationType: '' })

async function onCreateRelation(): Promise<void> {
  await store.createRelations([
    { from: form.from, to: form.to, relationType: form.relationType.trim() }
  ])
  emit('close', true)
}
</script>

<template>
  <div class="kg-create-relation">
    <label class="kg-field">
      <span class="kg-field__label">Da (entità)</span>
      <UiSelect
        :model-value="form.from"
        :options="props.entities"
        size="md"
        placeholder="Seleziona…"
        aria-label="Entità di partenza"
        @update:model-value="(v) => (form.from = String(v))"
      />
    </label>
    <div class="kg-field">
      <UiInput
        v-model="form.relationType"
        label="Tipo relazione"
        placeholder="es. conosce, lavora_con, si_trova_a"
      />
    </div>
    <label class="kg-field">
      <span class="kg-field__label">A (entità)</span>
      <UiSelect
        :model-value="form.to"
        :options="props.entities"
        size="md"
        placeholder="Seleziona…"
        aria-label="Entità di destinazione"
        @update:model-value="(v) => (form.to = String(v))"
      />
    </label>
    <div class="kg-dialog__actions">
      <UiButton variant="secondary" size="sm" @click="emit('close', false)">Annulla</UiButton>
      <UiButton
        variant="primary"
        size="sm"
        :disabled="!form.from || !form.to || !form.relationType.trim()"
        @click="onCreateRelation"
      >
        Crea
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.kg-create-relation {
  display: flex;
  flex-direction: column;
}

/* ── Form fields ───────────────────────────────────────────── */
.kg-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}

.kg-field__label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
}

/* ── Actions ───────────────────────────────────────────────── */
.kg-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
