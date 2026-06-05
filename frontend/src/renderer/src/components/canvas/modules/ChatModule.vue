<script setup lang="ts">
/**
 * ChatModule — Stub adapter for the Chat workspace tile.
 *
 * Replaced with real chat content in T8/T9. Accepts `params` already so the
 * tile leaf renderer can forward them without a future prop-contract change.
 */
import UiEmptyState from '../../ui/UiEmptyState.vue'

defineProps<{
  params?: Record<string, unknown>
}>()
</script>

<template>
  <div class="module-root">
    <UiEmptyState icon="message" title="Chat" subtitle="In arrivo" />
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
