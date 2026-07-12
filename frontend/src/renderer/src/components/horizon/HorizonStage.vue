<script setup lang="ts">
/**
 * HorizonStage — the presentation stage below the line: one artifact at a
 * time (3D / chart / whiteboard) with a museum caption and roman-numeral
 * navigation. Heavy viewers are lazy-loaded.
 */
import { computed, defineAsyncComponent } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import CADGenerationPlaceholder from '../chat/CADGenerationPlaceholder.vue'
import { toRoman } from '../../composables/horizon/horizonScene'
import type { HorizonArtifact } from '../../composables/horizon/horizonArtifacts'
import type { CadGenerationInfo } from '../../composables/useGenerationState'
import { useArtifactsStore } from '../../stores/artifacts'

const ImmersiveCADCanvas = defineAsyncComponent(() => import('../workspace/ImmersiveCADCanvas.vue'))
const ChartViewer = defineAsyncComponent(() => import('../chat/ChartViewer.vue'))
const TldrawCanvas = defineAsyncComponent(() => import('../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  artifacts: HorizonArtifact[]
  activeIndex: number
  /** Live CAD generation info (placeholder while the model bakes). */
  cadGeneration: CadGenerationInfo | null
}>()

const emit = defineEmits<{
  'update:activeIndex': [i: number]
  close: []
}>()

const artifactsStore = useArtifactsStore()

const active = computed(() => props.artifacts[props.activeIndex] ?? null)

const caption = computed(() => {
  if (!active.value) return ''
  const fig = `Fig. ${toRoman(props.activeIndex + 1)}`
  switch (active.value.kind) {
    case '3d':
      return `${fig} — ${active.value.cad?.model_name ?? 'modello 3D'} · trascina per ruotare`
    case 'chart':
      return `${fig} — grafico ${active.value.chart?.chart_type ?? ''}`.trim()
    case 'whiteboard':
      return `${fig} — lavagna`
  }
  return fig
})

function prev(): void {
  emit('update:activeIndex', Math.max(0, props.activeIndex - 1))
}

function next(): void {
  emit('update:activeIndex', Math.min(props.artifacts.length - 1, props.activeIndex + 1))
}

function saveBoard(boardId: string, snapshot: Record<string, unknown>): void {
  void artifactsStore.saveContent(boardId, { snapshot })
}
</script>

<template>
  <section class="hz-stage" aria-label="Risultato">
    <div class="hz-stage__frame">
      <CADGenerationPlaceholder v-if="cadGeneration" :generation="cadGeneration" />

      <ImmersiveCADCanvas
        v-else-if="active?.kind === '3d' && active.cad"
        :models="[active.cad]"
        :active-index="0"
        @close="emit('close')"
      />

      <ChartViewer
        v-else-if="active?.kind === 'chart' && active.chart"
        :key="active.chart.chart_id"
        :payload="active.chart"
      />

      <TldrawCanvas
        v-else-if="active?.kind === 'whiteboard' && active.board"
        :key="active.board.board_id"
        :board-id="active.board.board_id"
        @change="(snap: Record<string, unknown>) => saveBoard(active!.board!.board_id, snap)"
      />
    </div>

    <footer class="hz-stage__footer">
      <UiIconButton
        v-if="artifacts.length > 1"
        size="xs"
        variant="ghost"
        :disabled="activeIndex <= 0"
        label="Precedente"
        @click="prev"
      >
        <AppIcon name="chevron-left" :size="12" />
      </UiIconButton>

      <p class="hz-stage__caption">{{ caption }}</p>

      <UiIconButton
        v-if="artifacts.length > 1"
        size="xs"
        variant="ghost"
        :disabled="activeIndex >= artifacts.length - 1"
        label="Successivo"
        @click="next"
      >
        <AppIcon name="chevron-right" :size="12" />
      </UiIconButton>

      <span v-if="artifacts.length > 1" class="hz-stage__counter">
        {{ toRoman(activeIndex + 1) }} / {{ toRoman(artifacts.length) }}
      </span>

      <UiIconButton size="xs" variant="ghost" label="Chiudi il palco" @click="emit('close')">
        <AppIcon name="x" :size="12" />
      </UiIconButton>
    </footer>
  </section>
</template>

<style scoped>
.hz-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: min(88%, 980px);
  padding-bottom: clamp(14px, 3vh, 28px);
}

.hz-stage__frame {
  position: relative;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface-1);
}

.hz-stage__footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding-top: var(--space-2);
}

.hz-stage__caption {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
}

.hz-stage__counter {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.2em;
  color: var(--hz-ink-faint);
}
</style>
