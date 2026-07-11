<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    brand?: 'alce' | 'continuum'
  }>(),
  { brand: 'alce' }
)

const label = computed(() => (props.brand === 'alce' ? 'AL\\CE' : 'CONT\\NUUM'))
</script>

<template>
  <span class="brand-wordmark" :data-brand="brand" :aria-label="label" role="text">
    <template v-if="brand === 'alce'">
      <span class="brand-wordmark__seg">AL</span>
      <span class="brand-wordmark__slash" aria-hidden="true">\</span>
      <span class="brand-wordmark__seg">CE</span>
    </template>
    <template v-else>
      <span class="brand-wordmark__seg">CONT</span>
      <span class="brand-wordmark__slash" aria-hidden="true">\</span>
      <span class="brand-wordmark__seg">NUUM</span>
    </template>
  </span>
</template>

<style scoped>
.brand-wordmark {
  display: inline-flex;
  align-items: center;
  gap: 0.052em;
  font-family: var(--font-brand);
  font-size: 1em;
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
  line-height: 0.82;
  text-transform: uppercase;
  color: currentColor;
  vertical-align: -0.045em;
  white-space: nowrap;
}

.brand-wordmark[data-brand='continuum'] {
  gap: 0.06em;
}

.brand-wordmark__seg,
.brand-wordmark__slash {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 1em;
  line-height: 1;
}

.brand-wordmark__slash {
  margin-inline: 0.008em 0.014em;
  color: var(--accent);
}
</style>
