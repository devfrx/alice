<script setup lang="ts">
/**
 * Cad3dModule — Real adapter wrapping ImmersiveCADCanvas inside a workspace tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 *
 * - `params.artifactId` — string UUID of a single CAD artifact to open.
 *   The adapter fetches (or looks up) the artifact from the artifacts store
 *   and converts its `artifact_metadata` into a `CadModelPayload` for
 *   ImmersiveCADCanvas.
 *   T10 (useArtifactAutoOpen) must supply this key when opening the tile.
 *
 * ## Fallback
 * If `params.artifactId` is absent, the adapter renders all CAD artifacts
 * currently loaded in the store (newest first).  If the store is empty, a
 * UiEmptyState is shown.  The adapter does NOT automatically fetch — T10
 * is responsible for ensuring the store is populated before the tile opens.
 *
 * ## Emits from ImmersiveCADCanvas
 * - `update:activeIndex` — managed via a local `activeIndex` ref.
 * - `close` — ignored (the ModulePanel header handles tile removal).
 *
 * ## CadModelPayload derivation
 * Each CAD `Artifact` stores `{ model_name, export_url, format, description }`
 * in `artifact_metadata` (set by the backend parser in
 * `backend/services/artifacts/parsers.py`).  The adapter reads those fields
 * and falls back to `artifact.title` for the model name and
 * `artifact.download_url` for the export URL when the metadata keys are absent.
 */
import { computed, ref, watch, onMounted, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useArtifactsStore } from '../../../stores/artifacts'
import type { CadModelPayload } from '../../../types/chat'
import type { Artifact } from '../../../types/artifacts'

const ImmersiveCADCanvas = defineAsyncComponent(
  () => import('../../assistant/ImmersiveCADCanvas.vue')
)

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const store = useArtifactsStore()

/** Convert a store Artifact into the CadModelPayload expected by ImmersiveCADCanvas. */
function artifactToModel(artifact: Artifact): CadModelPayload {
  const meta = artifact.artifact_metadata
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

/** The pinned/target artifact when params.artifactId is provided. */
const targetArtifact = computed((): Artifact | null => {
  const id = props.params?.artifactId
  if (typeof id !== 'string' || id.length === 0) return null
  return store.findById(id)
})

/**
 * Model list passed to ImmersiveCADCanvas.
 * - When a specific artifactId is given: show only that artifact.
 * - Otherwise: show all CAD artifacts from the store (newest first, as stored).
 */
const models = computed((): CadModelPayload[] => {
  if (targetArtifact.value) {
    return [artifactToModel(targetArtifact.value)]
  }
  const cadArtifacts = store.items.filter(
    (a) => a.kind === 'cad_3d_text' || a.kind === 'cad_3d_image'
  )
  return cadArtifacts.map(artifactToModel)
})

/** Local active index — reset when the model list changes meaningfully. */
const activeIndex = ref(0)

watch(
  () => models.value.length,
  (newLen) => {
    if (activeIndex.value >= newLen) {
      activeIndex.value = Math.max(0, newLen - 1)
    }
  }
)

/**
 * If params.artifactId is provided but not yet in the store, fetch it.
 * This handles the case where T10 opens the tile before the artifact
 * has been loaded into the store.
 */
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
      activeIndex.value = 0
      await store.fetchById(id)
    } else {
      activeIndex.value = 0
    }
  }
)
</script>

<template>
  <div class="cad3d-module">
    <ImmersiveCADCanvas
      v-if="models.length > 0"
      :models="models"
      :active-index="activeIndex"
      @update:active-index="
        (i) => {
          activeIndex = i
        }
      "
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
  overflow: hidden;
}
</style>
