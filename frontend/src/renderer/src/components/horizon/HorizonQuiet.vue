<script setup lang="ts">
/** HorizonQuiet — the time-of-day greeting shown in the quiet state. */
import { computed } from 'vue'
import { useClock } from '../../composables/horizon/useClock'

const now = useClock()

const greeting = computed(() => {
  const h = now.value.getHours()
  if (h < 6) return 'Buonanotte.'
  if (h < 13) return 'Buongiorno.'
  if (h < 18) return 'Buon pomeriggio.'
  return 'Buonasera.'
})
</script>

<template>
  <p class="hz-quiet">{{ greeting }}</p>
</template>

<style scoped>
.hz-quiet {
  margin: 0 0 clamp(28px, 6vh, 64px);
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(28px, 4.6vmin, 52px);
  letter-spacing: 0.01em;
  color: var(--hz-ink);
  user-select: none;
}
</style>
