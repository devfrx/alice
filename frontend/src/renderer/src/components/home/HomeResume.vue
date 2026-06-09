<script setup lang="ts">
/**
 * "Riprendi" — the most recent non-empty conversations as dated dossier
 * entries. Real data only: empty drafts are filtered out, and a warm empty
 * state shows on first run (no fabricated entries).
 */
import { computed } from 'vue'
import type { ConversationSummary } from '../../types/chat'
import UiEmptyState from '../ui/UiEmptyState.vue'
import HomeResumeEntry from './HomeResumeEntry.vue'

const props = defineProps<{ conversations: ConversationSummary[] }>()
const emit = defineEmits<{ open: [string] }>()

const MAX = 4

const recent = computed<ConversationSummary[]>(() =>
  [...props.conversations]
    .filter((c) => c.message_count > 0)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, MAX)
)
</script>

<template>
  <section class="hr" aria-label="Riprendi">
    <p class="hr__label">
      <span>Riprendi</span>
      <span class="hr__rule" aria-hidden="true" />
      <span v-if="recent.length">{{ recent.length }} thread</span>
    </p>

    <div v-if="recent.length" class="hr__list">
      <HomeResumeEntry
        v-for="c in recent"
        :key="c.id"
        :conversation="c"
        @open="(id) => emit('open', id)"
      />
    </div>

    <UiEmptyState
      v-else
      compact
      icon="message"
      title="Iniziamo da qui."
      subtitle="Le conversazioni che apri compariranno qui per riprenderle al volo."
    />
  </section>
</template>

<style scoped>
.hr {
  margin-top: var(--space-14);
}

.hr__label {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin: 0 0 var(--space-1);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--tracking-wider);
  text-transform: uppercase;
}

.hr__rule {
  flex: 1;
  height: 1px;
  background: var(--border);
}

.hr__list {
  display: flex;
  flex-direction: column;
}

/* No trailing rule before the colophon's own top border. */
.hr__list :deep(.hre:last-child) {
  border-bottom: none;
}
</style>
