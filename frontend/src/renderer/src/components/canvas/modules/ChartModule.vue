<script setup lang="ts">
/**
 * ChartModule — Real adapter wrapping ChartViewer inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.chartPayload` — a full {@link ChartPayload} object
 *   `{ chart_id, chart_url, title, chart_type, created_at }`.
 *   ChartViewer fetches the ECharts spec from `chart_url` itself, so the
 *   adapter only needs to forward this object.  T10 (useArtifactAutoOpen)
 *   must supply this key when opening the tile.
 *
 * If `params.chartPayload` is absent or malformed, a UiEmptyState is
 * rendered instead of crashing.
 */
import { computed, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import type { ChartPayload } from '../../../types/chat'

const ChartViewer = defineAsyncComponent(() => import('../../chat/ChartViewer.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

/** Resolve and type-guard the ChartPayload from params. */
const chartPayload = computed((): ChartPayload | null => {
  const p = props.params?.chartPayload
  if (
    p &&
    typeof p === 'object' &&
    !Array.isArray(p) &&
    typeof (p as Record<string, unknown>).chart_id === 'string' &&
    typeof (p as Record<string, unknown>).chart_url === 'string' &&
    typeof (p as Record<string, unknown>).chart_type === 'string'
  ) {
    return p as ChartPayload
  }
  return null
})
</script>

<template>
  <div class="chart-module">
    <ChartViewer v-if="chartPayload" :key="chartPayload.chart_id" :payload="chartPayload" />
    <UiEmptyState
      v-else
      icon="bar-chart"
      title="Nessun grafico"
      subtitle="Apri un grafico dalla chat per visualizzarlo qui."
    />
  </div>
</template>

<style scoped>
.chart-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
