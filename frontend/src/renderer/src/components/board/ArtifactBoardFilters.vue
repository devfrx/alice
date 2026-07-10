<script setup lang="ts">
/**
 * ArtifactBoardFilters.vue — Filter bar for the Bacheca view.
 *
 * Holds the kind chips, the "pinned only" toggle and the conversation
 * dropdown. Pure controlled component: all state lives in the parent.
 */
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiSelect, { type UiSelectOption } from '../ui/UiSelect.vue'
import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'
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

const KIND_OPTIONS: UiSegmentedOption[] = [
  { value: 'all', label: 'Tutti' },
  { value: 'cad_3d_text', label: '3D da testo' },
  { value: 'cad_3d_image', label: '3D da immagine' }
]

/** Bound select value (writable computed; widened to accept UiSelect's `string | number`). */
const conversationModel = computed<string | number>({
  get: () => props.conversationFilter,
  set: (v) => emit('update:conversationFilter', String(v))
})

/** Options for the conversation filter, with the leading "Tutte" entry. */
const conversationOptions = computed<UiSelectOption[]>(() => [
  { value: 'all', label: 'Tutte' },
  ...props.conversations.map((c) => ({ value: c.id, label: c.title || 'Senza titolo' }))
])
</script>

<template>
  <div class="artifact-filters">
    <UiSegmented
      :equal="false"
      :model-value="kindFilter"
      :options="KIND_OPTIONS"
      aria-label="Filtra per tipo"
      @update:model-value="(v) => emit('update:kindFilter', v as ArtifactKind | 'all')"
    />

    <label
      class="artifact-filters__pinned"
      :class="{ 'artifact-filters__pinned--active': pinnedOnly }"
    >
      <input
        type="checkbox"
        :checked="pinnedOnly"
        @change="emit('update:pinnedOnly', ($event.target as HTMLInputElement).checked)"
      />
      <AppIcon name="pin" :size="13" />
      <span>Solo pinnati</span>
    </label>

    <label class="artifact-filters__conv">
      <span class="artifact-filters__conv-label">Conversazione</span>
      <UiSelect
        v-model="conversationModel"
        :options="conversationOptions"
        size="sm"
        aria-label="Conversazione"
        class="artifact-filters__select"
      />
    </label>
  </div>
</template>

<style scoped>
.artifact-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-6) var(--space-4);
  background: transparent;
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
  min-width: 200px;
}

@media (max-width: 720px) {
  .artifact-filters {
    padding: var(--space-2) var(--space-4) var(--space-3);
  }

  .artifact-filters__conv {
    margin-left: 0;
  }

  .artifact-filters__select {
    min-width: 160px;
  }
}
</style>
