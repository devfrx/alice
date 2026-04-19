<script setup lang="ts">
/**
 * ArtifactBoardFilters.vue — Filter bar for the Bacheca view.
 *
 * Holds the kind chips, the "pinned only" toggle and the conversation
 * dropdown. Pure controlled component: all state lives in the parent.
 */
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import type { ArtifactKind } from '../../types/artifacts'
import type { ConversationSummary } from '../../types/chat'

const props = defineProps<{
    kindFilter: ArtifactKind | 'all'
    pinnedOnly: boolean
    conversationFilter: string | 'all'
    conversations: ConversationSummary[]
}>()

const emit = defineEmits<{
    'update:kindFilter': [value: ArtifactKind | 'all']
    'update:pinnedOnly': [value: boolean]
    'update:conversationFilter': [value: string | 'all']
}>()

interface KindOption {
    value: ArtifactKind | 'all'
    label: string
}

const KIND_OPTIONS: KindOption[] = [
    { value: 'all', label: 'Tutti' },
    { value: 'cad_3d_text', label: '3D da testo' },
    { value: 'cad_3d_image', label: '3D da immagine' },
]

/** Bound select value (must be a writable computed for v-model). */
const conversationModel = computed({
    get: () => props.conversationFilter,
    set: (v) => emit('update:conversationFilter', v),
})
</script>

<template>
    <div class="artifact-filters">
        <div class="artifact-filters__chips" role="tablist" aria-label="Filtra per tipo">
            <button v-for="opt in KIND_OPTIONS" :key="opt.value" class="artifact-filters__chip"
                :class="{ 'artifact-filters__chip--active': kindFilter === opt.value }" role="tab"
                :aria-selected="kindFilter === opt.value" @click="emit('update:kindFilter', opt.value)">
                {{ opt.label }}
            </button>
        </div>

        <label class="artifact-filters__pinned" :class="{ 'artifact-filters__pinned--active': pinnedOnly }">
            <input type="checkbox" :checked="pinnedOnly"
                @change="emit('update:pinnedOnly', ($event.target as HTMLInputElement).checked)" />
            <AppIcon name="pin" :size="13" />
            <span>Solo pinnati</span>
        </label>

        <label class="artifact-filters__conv">
            <span class="artifact-filters__conv-label">Conversazione</span>
            <select v-model="conversationModel" class="artifact-filters__select">
                <option value="all">Tutte</option>
                <option v-for="c in conversations" :key="c.id" :value="c.id">
                    {{ c.title || 'Senza titolo' }}
                </option>
            </select>
        </label>
    </div>
</template>

<style scoped>
.artifact-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
    background: var(--surface-1);
}

/* ── Kind chips ── */
.artifact-filters__chips {
    display: inline-flex;
    gap: var(--space-1);
    padding: 2px;
    border-radius: var(--radius-md);
    background: var(--surface-2);
    border: 1px solid var(--border);
}

.artifact-filters__chip {
    padding: var(--space-1-5) var(--space-3);
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-xs);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition:
        color var(--transition-fast),
        background var(--transition-fast);
}

.artifact-filters__chip:hover {
    color: var(--text-primary);
}

.artifact-filters__chip--active {
    color: var(--accent);
    background: var(--accent-dim);
}

/* ── Pinned toggle ── */
.artifact-filters__pinned {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: var(--space-1-5) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    user-select: none;
    transition:
        color var(--transition-fast),
        border-color var(--transition-fast),
        background var(--transition-fast);
}

.artifact-filters__pinned input {
    appearance: none;
    width: 0;
    height: 0;
    margin: 0;
    pointer-events: none;
}

.artifact-filters__pinned:hover {
    color: var(--text-primary);
    border-color: var(--border-hover);
}

.artifact-filters__pinned--active {
    color: var(--accent);
    border-color: var(--accent-border);
    background: var(--accent-dim);
}

/* ── Conversation select ── */
.artifact-filters__conv {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
    color: var(--text-muted);
    font-size: var(--text-xs);
}

.artifact-filters__conv-label {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: var(--text-2xs);
}

.artifact-filters__select {
    background: var(--surface-2);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 6px var(--space-2);
    font-size: var(--text-xs);
    font-family: inherit;
    min-width: 200px;
    cursor: pointer;
}

.artifact-filters__select:focus {
    outline: none;
    border-color: var(--accent-border);
    box-shadow: 0 0 0 2px var(--accent-glow);
}
</style>
