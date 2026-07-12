<script setup lang="ts">
/**
 * KgCreateEntityDialog — Form for creating a new Knowledge Graph entity.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (created) or `false` (cancelled).
 */
import { reactive } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'
import UiButton from '../ui/UiButton.vue'
import UiInput from '../ui/UiInput.vue'
import UiTextarea from '../ui/UiTextarea.vue'

const emit = defineEmits<{ close: [result: boolean] }>()

const store = useMcpMemoryStore()

const form = reactive({ name: '', entityType: '', observationsText: '' })

async function onCreate(): Promise<void> {
  const observations = form.observationsText
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  await store.createEntities([
    { name: form.name.trim(), entityType: form.entityType.trim(), observations }
  ])
  emit('close', true)
}
</script>

<template>
  <div class="kg-create-entity">
    <div class="kg-field">
      <UiInput v-model="form.name" label="Nome" placeholder="es. Mario Rossi" />
    </div>
    <div class="kg-field">
      <UiInput v-model="form.entityType" label="Tipo" placeholder="es. persona, luogo, concetto" />
    </div>
    <div class="kg-field">
      <UiTextarea
        v-model="form.observationsText"
        label="Osservazioni (una per riga)"
        :rows="3"
        placeholder="es. Lavora come ingegnere&#10;Vive a Milano"
      />
    </div>
    <div class="kg-dialog__actions">
      <UiButton variant="secondary" size="sm" @click="emit('close', false)">Annulla</UiButton>
      <UiButton
        variant="primary"
        size="sm"
        :disabled="!form.name.trim() || !form.entityType.trim()"
        @click="onCreate"
      >
        Crea
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.kg-create-entity {
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

/* ── Actions ───────────────────────────────────────────────── */
.kg-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
