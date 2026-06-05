<script setup lang="ts">
/**
 * ChartModule — Stub adapter for the Grafico (chart) workspace tile.
 *
 * Replaced with real chart content in T8. Accepts `params` already so the
 * tile leaf renderer can forward them without a future prop-contract change.
 */
import UiEmptyState from '../../ui/UiEmptyState.vue'

defineProps<{
  params?: Record<string, unknown>
}>()
</script>

<template>
  <div class="module-root">
    <UiEmptyState icon="bar-chart" title="Grafico" subtitle="In arrivo" />
  </div>
</template>

<style scoped>
.module-root {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
