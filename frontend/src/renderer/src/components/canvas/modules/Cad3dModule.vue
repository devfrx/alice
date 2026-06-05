<script setup lang="ts">
/**
 * Cad3dModule — Stub adapter for the 3D (TRELLIS) workspace tile.
 *
 * Replaced with real 3D content in T8. Accepts `params` already so the
 * tile leaf renderer can forward them without a future prop-contract change.
 */
import UiEmptyState from '../../ui/UiEmptyState.vue'

defineProps<{
  params?: Record<string, unknown>
}>()
</script>

<template>
  <div class="module-root">
    <UiEmptyState icon="box-3d" title="3D" subtitle="In arrivo" />
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
