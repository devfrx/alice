<script setup lang="ts">
/**
 * KgAddObservationDialog — Form for adding observations to a KG entity.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (added) or `false` (cancelled).
 */
import { ref } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'
import UiButton from '../ui/UiButton.vue'
import UiTextarea from '../ui/UiTextarea.vue'

const props = defineProps<{
  entityName: string
}>()

const emit = defineEmits<{ close: [result: boolean] }>()

const store = useMcpMemoryStore()

const text = ref('')

async function onAdd(): Promise<void> {
  const contents = text.value
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  if (contents.length > 0) {
    await store.addObservations(props.entityName, contents)
  }
  emit('close', true)
}
</script>

<template>
  <div class="kg-add-observation">
    <UiTextarea
      v-model="text"
      label="Nuove osservazioni (una per riga)"
      :rows="3"
      placeholder="es. Ha un cane di nome Rex"
    />
    <div class="kg-dialog__actions">
      <UiButton variant="secondary" size="sm" @click="emit('close', false)">Annulla</UiButton>
      <UiButton variant="primary" size="sm" :disabled="!text.trim()" @click="onAdd">
        Aggiungi
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.kg-add-observation {
  display: flex;
  flex-direction: column;
}

/* ── Actions ───────────────────────────────────────────────── */
.kg-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
