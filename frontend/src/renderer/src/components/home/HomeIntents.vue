<script setup lang="ts">
/**
 * Intent chips. Most chips prefill the composer; "Riprendi l'ultima" emits a
 * dedicated event the parent handles by reopening the most recent thread.
 */
import AppIcon from '../ui/AppIcon.vue'
import UiChip from '../ui/UiChip.vue'

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
    <UiChip
      v-for="intent in intents"
      :key="intent.label"
      size="md"
      class="hi__chip"
      @click="activate(intent)"
    >
      <template v-if="intent.lead" #icon>
        <AppIcon name="plus" :size="13" />
      </template>
      {{ intent.label }}
    </UiChip>
  </div>
</template>

<style scoped>
.hi {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

/* Hero surface reads larger than the kit's compact chip scale (max "md" is
   still a utility-density chip) — restore the original padding/type size. */
.hi__chip.ui-chip {
  padding: var(--space-2) var(--space-3-5);
  font-size: var(--text-sm);
}

.hi__chip :deep(.ui-chip__icon) {
  color: var(--accent);
}
</style>
