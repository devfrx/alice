<script setup lang="ts">
/**
 * ChartModule — Real adapter wrapping ChartViewer inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.chartPayload` — a full {@link ChartPayload} object
 *   `{ chart_id, chart_url, title, chart_type, created_at }`.
 *   ChartViewer fetches the ECharts spec via the artifacts content API,
 *   so the adapter only needs to forward this object. useArtifactAutoOpen
 *   supplies this key when auto-opening the tile for a freshly-generated chart.
 *
 * ## Multi-chart handling
 * When a conversation contains several charts, a {@link ModuleSelectorBar} lets
 * the user switch between them. Selection is resolved by
 * {@link useModuleItemSelection}: manual pick → `chartPayload` param →
 * most-recent chart. The chart list derives from messages (extractCharts),
 * not from a dedicated store.
 *
 * ## Fallback
 * Only when no chart exists at all is a UiEmptyState rendered.
 */
import { computed, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useChatStore } from '@renderer/stores/chat'
import { extractCharts, isChartPayload } from '@renderer/types/chat'
import { useModuleItemSelection } from '@renderer/composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'
import type { ChartPayload } from '@renderer/types/chat'

const ChartViewer = defineAsyncComponent(() => import('../../chat/ChartViewer.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()

/** Charts in the active conversation, oldest → newest (derived from messages). */
const charts = computed<ChartPayload[]>(() => extractCharts(chatStore.messages))

const { current, currentId, select } = useModuleItemSelection<ChartPayload>({
  items: () => charts.value,
  getId: (c) => c.chart_id,
  preferredId: () => {
    const p = props.params?.chartPayload
    return isChartPayload(p) ? p.chart_id : null
  }
})

/**
 * Chart to display: the resolved selection, falling back to the raw param
 * payload if the message list hasn't populated yet (initial-load race).
 */
const chartPayload = computed<ChartPayload | null>(() => {
  if (current.value) return current.value
  const p = props.params?.chartPayload
  return isChartPayload(p) ? p : null
})

/** One selector option per chart in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  charts.value.map((c, i) => ({ value: c.chart_id, label: c.title || `Grafico ${i + 1}` }))
)
</script>

<template>
  <div class="chart-module">
    <ModuleSelectorBar
      :model-value="currentId"
      :options="options"
      aria-label="Seleziona grafico"
      @update:model-value="(v) => select(String(v))"
    />
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
