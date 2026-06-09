<script setup lang="ts">
/**
 * KgAddObservationDialog — Form for adding observations to a KG entity.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (added) or `false` (cancelled).
 */
import { ref } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'

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
        <label class="kg-field">
            <span class="kg-field__label">Nuove osservazioni (una per riga)</span>
            <textarea v-model="text" class="kg-textarea" rows="3"
                placeholder="es. Ha un cane di nome Rex" />
        </label>
        <div class="kg-dialog__actions">
            <button class="kg-btn kg-btn--secondary" @click="emit('close', false)">Annulla</button>
            <button class="kg-btn kg-btn--accent" :disabled="!text.trim()"
                @click="onAdd">Aggiungi</button>
        </div>
    </div>
</template>

<style scoped>
.kg-add-observation {
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

.kg-textarea {
    padding: var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-family: inherit;
    outline: none;
    resize: vertical;
    transition: border-color var(--transition-fast);
}

.kg-textarea:focus {
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
