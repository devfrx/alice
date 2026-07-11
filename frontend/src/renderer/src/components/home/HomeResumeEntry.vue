<script setup lang="ts">
/** One dossier entry: when (mono, accent) · title · meta · arrow. */
import type { ConversationSummary } from '../../types/chat'
import { formatRelativeTime } from '../../utils/relativeTime'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{ conversation: ConversationSummary }>()
const emit = defineEmits<{ open: [string] }>()

function metaLabel(c: ConversationSummary): string {
  const n = c.message_count
  return `${n} ${n === 1 ? 'messaggio' : 'messaggi'}`
}
</script>

<template>
  <button class="hre" type="button" @click="emit('open', props.conversation.id)">
    <span class="hre__when">{{ formatRelativeTime(props.conversation.updated_at) }}</span>
    <span class="hre__body">
      <span class="hre__title">{{ props.conversation.title || 'Conversazione senza titolo' }}</span>
      <span class="hre__meta">{{ metaLabel(props.conversation) }}</span>
    </span>
    <AppIcon class="hre__go" name="chevron-right" :size="15" />
  </button>
</template>

<style scoped>
.hre {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: baseline;
  gap: var(--space-4);
  width: 100%;
  padding: var(--space-4) var(--space-2);
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.hre:hover {
  background: var(--accent-faint);
}

.hre__when {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--accent);
  letter-spacing: var(--tracking-normal);
}

.hre__body {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.hre__title {
  color: var(--text-primary);
  font-size: var(--text-md);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hre__meta {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.hre__go {
  align-self: center;
  color: var(--text-muted);
  transition: color var(--transition-fast);
}

.hre:hover .hre__go {
  color: var(--accent);
}
</style>
