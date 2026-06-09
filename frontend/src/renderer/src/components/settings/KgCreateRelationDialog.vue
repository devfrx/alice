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

const props = defineProps<{
    entities: UiSelectOption[]
}>()

const emit = defineEmits<{ close: [result: boolean] }>()

const store = useMcpMemoryStore()

const form = reactive({ from: '', to: '', relationType: '' })

async function onCreateRelation(): Promise<void> {
    await store.createRelations([
        { from: form.from, to: form.to, relationType: form.relationType.trim() },
    ])
    emit('close', true)
}
</script>

<template>
    <div class="kg-create-relation">
        <label class="kg-field">
            <span class="kg-field__label">Da (entità)</span>
            <UiSelect :model-value="form.from" :options="props.entities" size="md"
                placeholder="Seleziona…" aria-label="Entità di partenza"
                @update:model-value="(v) => (form.from = String(v))" />
        </label>
        <label class="kg-field">
            <span class="kg-field__label">Tipo relazione</span>
            <input v-model="form.relationType" type="text" class="kg-input"
                placeholder="es. conosce, lavora_con, si_trova_a" />
        </label>
        <label class="kg-field">
            <span class="kg-field__label">A (entità)</span>
            <UiSelect :model-value="form.to" :options="props.entities" size="md"
                placeholder="Seleziona…" aria-label="Entità di destinazione"
                @update:model-value="(v) => (form.to = String(v))" />
        </label>
        <div class="kg-dialog__actions">
            <button class="kg-btn kg-btn--secondary" @click="emit('close', false)">Annulla</button>
            <button class="kg-btn kg-btn--accent"
                :disabled="!form.from || !form.to || !form.relationType.trim()"
                @click="onCreateRelation">Crea</button>
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

.kg-input {
    padding: var(--space-1) var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-family: inherit;
    outline: none;
    transition: border-color var(--transition-fast);
}

.kg-input:focus {
    border-color: var(--accent-border);
}

/* ── Actions ───────────────────────────────────────────────── */
.kg-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    margin-top: var(--space-2);
}

.kg-btn {
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    cursor: pointer;
    border: 1px solid transparent;
    transition: all var(--transition-fast);
}

.kg-btn--accent {
    background: var(--accent-dim);
    border-color: var(--accent-border);
    color: var(--accent);
}

.kg-btn--accent:hover:not(:disabled) {
    background: var(--accent-light);
    border-color: var(--accent);
}

.kg-btn--secondary {
    background: var(--surface-3);
    border-color: var(--border);
    color: var(--text-secondary);
}

.kg-btn--secondary:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--text-primary);
}

.kg-btn:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
}
</style>
