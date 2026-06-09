<script setup lang="ts">
/**
 * Intent chips. Most chips prefill the composer; "Riprendi l'ultima" emits a
 * dedicated event the parent handles by reopening the most recent thread.
 */
import AppIcon from '../ui/AppIcon.vue'

const emit = defineEmits<{ prefill: [string]; 'resume-last': [] }>()

interface Intent {
  label: string
  prefill?: string
  resumeLast?: boolean
  lead?: boolean
}

const intents: Intent[] = [
  { label: 'Pianifica un lavoro', prefill: 'Aiutami a pianificare: ', lead: true },
  { label: 'Cerca nei file', prefill: 'Cerca nei miei file: ' },
  { label: 'Genera un grafico', prefill: 'Genera un grafico che mostri ' },
  { label: "Riprendi l'ultima", resumeLast: true }
]

function activate(intent: Intent): void {
  if (intent.resumeLast) emit('resume-last')
  else if (intent.prefill) emit('prefill', intent.prefill)
}
</script>

<template>
  <div class="hi">
    <button
      v-for="intent in intents"
      :key="intent.label"
      class="hi__chip"
      type="button"
      @click="activate(intent)"
    >
      <AppIcon v-if="intent.lead" name="plus" :size="13" />
      <span>{{ intent.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.hi {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.hi__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-3-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.hi__chip:hover {
  border-color: var(--accent-border);
  color: var(--text-primary);
}

.hi__chip :deep(svg) {
  color: var(--accent);
}
</style>
