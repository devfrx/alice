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
 * ## Fallback
 * If `params.chartPayload` is absent or malformed, the adapter falls back to
 * the most-recent chart in the active conversation (`chartsStore.currentChart`),
 * mirroring WhiteboardModule (`store.currentBoard`) and Cad3dModule
 * (`store.items`). Only when no chart exists at all is a UiEmptyState rendered.
 */
import { computed, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useChartsStore, isChartPayload } from '../../../stores/charts'
import type { ChartPayload } from '../../../types/chat'

const ChartViewer = defineAsyncComponent(() => import('../../chat/ChartViewer.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const chartsStore = useChartsStore()

/**
 * Resolve the ChartPayload to display:
 * 1. The explicit `chartPayload` param (set by useArtifactAutoOpen on open).
 * 2. Fallback: the most-recent chart in the active conversation.
 */
const chartPayload = computed((): ChartPayload | null => {
  const p = props.params?.chartPayload
  if (isChartPayload(p)) return p
  return chartsStore.currentChart
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
