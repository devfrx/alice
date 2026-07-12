<script setup lang="ts">
/**
 * Cad3dModule — Real adapter wrapping ImmersiveCADCanvas inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.artifactId` — string UUID of a CAD artifact to focus.
 *   useArtifactAutoOpen supplies this key when auto-opening the tile for a
 *   freshly-generated model.
 *
 * ## Multi-model handling
 * The tile always carries every CAD model in the conversation; a
 * {@link ModuleSelectorBar} switches between them. Selection is resolved by
 * {@link useModuleItemSelection} (manual pick → `artifactId` param →
 * most-recent) and drives ImmersiveCADCanvas's `activeIndex`. The canvas's own
 * inline prev/next nav is hidden here (`hide-nav`) since the bar replaces it;
 * assistant mode keeps that nav.
 *
 * ## CadModelPayload derivation
 * Each CAD `Artifact` stores `{ model_name, export_url, format, description }`
 * in `artifact_metadata` (set by the backend parser). The adapter reads those
 * fields and falls back to `artifact.title` / `artifact.download_url` when a
 * metadata key is absent.
 */
import { computed, defineAsyncComponent, onMounted, watch } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useArtifactsStore } from '@renderer/stores/artifacts'
import { useModuleItemSelection } from '@renderer/composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'
import type { CadModelPayload } from '@renderer/types/chat'
import type { Artifact } from '@renderer/types/artifacts'

const ImmersiveCADCanvas = defineAsyncComponent(
  () => import('../../assistant/ImmersiveCADCanvas.vue')
)

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const store = useArtifactsStore()

/** All CAD artifacts currently in the store (oldest → newest as stored end). */
const cadArtifacts = computed<Artifact[]>(() =>
  store.items.filter((a) => a.kind === 'cad_3d_text' || a.kind === 'cad_3d_image')
)

const { currentId, select } = useModuleItemSelection<Artifact>({
  items: () => cadArtifacts.value,
  getId: (a) => a.id,
  preferredId: () => {
    const id = props.params?.artifactId
    return typeof id === 'string' && id.length > 0 ? id : null
  }
})

/** Convert a store Artifact into the CadModelPayload expected by the canvas. */
function artifactToModel(artifact: Artifact): CadModelPayload {
  const meta = artifact.artifact_metadata ?? {}
  return {
    model_name:
      typeof meta.model_name === 'string' && meta.model_name.length > 0
        ? meta.model_name
        : artifact.title,
    export_url:
      typeof meta.export_url === 'string' && meta.export_url.length > 0
        ? meta.export_url
        : artifact.download_url,
    format: typeof meta.format === 'string' && meta.format.length > 0 ? meta.format : 'glb',
    size_bytes: artifact.size_bytes,
    description: typeof meta.description === 'string' ? meta.description : undefined
  }
}

/** Extract a non-empty model_name from artifact metadata, or ''. */
function modelNameOf(meta: Record<string, unknown>): string {
  return typeof meta.model_name === 'string' && meta.model_name.length > 0 ? meta.model_name : ''
}

/** Full model list handed to the canvas (kept stable so navigation works). */
const models = computed<CadModelPayload[]>(() => cadArtifacts.value.map(artifactToModel))

/** Index of the resolved selection within the model list. */
const activeIndex = computed<number>(() => {
  const idx = cadArtifacts.value.findIndex((a) => a.id === currentId.value)
  return idx >= 0 ? idx : Math.max(0, cadArtifacts.value.length - 1)
})

/** One selector option per CAD model in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  cadArtifacts.value.map((a, i) => ({
    value: a.id,
    label: modelNameOf(a.artifact_metadata ?? {}) || a.title || `Modello ${i + 1}`
  }))
)

/** Map a canvas-driven index change back onto the selection. */
function onActiveIndexUpdate(i: number): void {
  const artifact = cadArtifacts.value[i]
  if (artifact) select(artifact.id)
}

/** If a param artifactId is provided but not yet in the store, fetch it. */
onMounted(async () => {
  const id = props.params?.artifactId
  if (typeof id === 'string' && id.length > 0 && !store.findById(id)) {
    await store.fetchById(id)
  }
})

watch(
  () => props.params?.artifactId,
  async (id) => {
    if (typeof id === 'string' && id.length > 0 && !store.findById(id)) {
      await store.fetchById(id)
    }
  }
)
</script>

<template>
  <div class="cad3d-module">
    <ModuleSelectorBar
      :model-value="currentId"
      :options="options"
      aria-label="Seleziona modello 3D"
      @update:model-value="(v) => select(String(v))"
    />
    <ImmersiveCADCanvas
      v-if="models.length > 0"
      :models="models"
      :active-index="activeIndex"
      hide-nav
      @update:active-index="onActiveIndexUpdate"
      @close="
        () => {
          /* handled by ModulePanel header */
        }
      "
    />
    <UiEmptyState
      v-else
      icon="box-3d"
      title="Nessun modello 3D"
      subtitle="Genera un modello 3D nella chat per visualizzarlo qui."
    />
  </div>
</template>

<style scoped>
.cad3d-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Let the canvas fill the height remaining under the selector bar. */
.cad3d-module :deep(.side-cad) {
  flex: 1 1 0;
  min-height: 0;
}
</style>
