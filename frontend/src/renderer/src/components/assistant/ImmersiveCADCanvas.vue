<script setup lang="ts">
/**
 * ImmersiveCADCanvas.vue â€” Side-panel 3D model viewer for assistant mode.
 *
 * Renders as a full-height side panel on the right, showing one model
 * at a time with prev/next navigation when multiple models exist.
 * The canvas background matches --surface-0 so it integrates seamlessly
 * with the assistant dark theme.
 *
 * Props receive the full list of CAD models + the active index from the parent.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { resolveBackendUrl } from '../../services/api'
import type { CadModelPayload } from '../../types/chat'

const props = defineProps<{
  /** All CAD models in the conversation. */
  models: CadModelPayload[]
  /** Index of the currently displayed model. */
  activeIndex: number
}>()

const emit = defineEmits<{
  close: []
  'update:activeIndex': [index: number]
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')
const autoRotate = ref(true)
const wireframe = ref(false)

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let animFrameId = 0
let resizeObserver: ResizeObserver | null = null
let loadedModel: THREE.Group | null = null

let initialCameraPos = new THREE.Vector3()
let initialControlsTarget = new THREE.Vector3()

const BG_COLOR = 0x161616

const activeModel = computed(() => props.models[props.activeIndex] ?? null)
const hasMultiple = computed(() => props.models.length > 1)
const canPrev = computed(() => props.activeIndex > 0)
const canNext = computed(() => props.activeIndex < props.models.length - 1)

function goPrev(): void {
  if (canPrev.value) emit('update:activeIndex', props.activeIndex - 1)
}

function goNext(): void {
  if (canNext.value) emit('update:activeIndex', props.activeIndex + 1)
}

function initScene(container: HTMLDivElement): void {
  const w = container.clientWidth
  const h = container.clientHeight

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(w, h)
  renderer.setClearColor(BG_COLOR)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.05
  renderer.outputColorSpace = THREE.SRGBColorSpace
  container.appendChild(renderer.domElement)

  scene = new THREE.Scene()
  scene.fog = new THREE.FogExp2(BG_COLOR, 0.035)

  camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 500)
  camera.position.set(3, 2, 3)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.06
  controls.autoRotate = true
  controls.autoRotateSpeed = 1.2
  controls.maxPolarAngle = Math.PI * 0.85
  controls.minDistance = 0.3
  controls.enablePan = false

  /* Warm three-point lighting */
  scene.add(new THREE.AmbientLight(0xfaf5ee, 0.25))

  const keyLight = new THREE.DirectionalLight(0xfff5e6, 0.9)
  keyLight.position.set(4, 6, 5)
  scene.add(keyLight)

  const fillLight = new THREE.DirectionalLight(0xe8dcc8, 0.25)
  fillLight.position.set(-3, 3, -2)
  scene.add(fillLight)

  const rimLight = new THREE.DirectionalLight(0xd0d8e8, 0.25)
  rimLight.position.set(-1, -2, -4)
  scene.add(rimLight)
}

function fitCameraToModel(model: THREE.Object3D): void {
  if (!camera || !controls) return
  const box = new THREE.Box3().setFromObject(model)
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z)
  const fov = camera.fov * (Math.PI / 180)
  const dist = maxDim / (2 * Math.tan(fov / 2)) * 2.0

  camera.position.set(
    center.x + dist * 0.55,
    center.y + dist * 0.3,
    center.z + dist * 0.55,
  )
  controls.target.copy(center)
  camera.near = dist * 0.005
  camera.far = dist * 25
  camera.updateProjectionMatrix()
  controls.update()

  initialCameraPos.copy(camera.position)
  initialControlsTarget.copy(controls.target)
}

function loadModel(url: string): void {
  if (!scene) return
  loading.value = true
  errorMsg.value = ''

  if (loadedModel) {
    disposeModel(loadedModel)
    scene.remove(loadedModel)
    loadedModel = null
  }

  const resolved = resolveBackendUrl(url)
  const loader = new GLTFLoader()
  loader.load(
    resolved,
    (gltf) => {
      loadedModel = gltf.scene
      scene!.add(loadedModel)
      fitCameraToModel(loadedModel)
      loading.value = false
    },
    undefined,
    (err) => {
      errorMsg.value = err instanceof Error ? err.message : 'Errore caricamento modello 3D'
      loading.value = false
    },
  )
}

function disposeModel(model: THREE.Group): void {
  model.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.geometry?.dispose()
      if (Array.isArray(child.material)) {
        child.material.forEach((m) => { m.map?.dispose(); m.dispose() })
      } else if (child.material) {
        ; (child.material as THREE.MeshStandardMaterial).map?.dispose()
        child.material.dispose()
      }
    }
  })
}

function animate(): void {
  animFrameId = requestAnimationFrame(animate)
  if (controls) {
    controls.autoRotate = autoRotate.value
    controls.update()
  }
  if (renderer && scene && camera) {
    renderer.render(scene, camera)
  }
}

function handleResize(): void {
  const container = containerRef.value
  if (!container || !renderer || !camera) return
  const w = container.clientWidth
  const h = container.clientHeight
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

/* Reload when active model changes */
watch(activeModel, (model) => {
  if (model && scene) {
    wireframe.value = false
    loadModel(model.export_url)
  }
})

function toggleAutoRotate(): void { autoRotate.value = !autoRotate.value }

function toggleWireframe(): void {
  wireframe.value = !wireframe.value
  loadedModel?.traverse((child) => {
    if (child instanceof THREE.Mesh && child.material && 'wireframe' in child.material) {
      ; (child.material as THREE.MeshStandardMaterial).wireframe = wireframe.value
    }
  })
}

function resetCamera(): void {
  if (!camera || !controls) return
  camera.position.copy(initialCameraPos)
  controls.target.copy(initialControlsTarget)
  controls.update()
}

function downloadModel(): void {
  const model = activeModel.value
  if (!model) return
  const url = resolveBackendUrl(model.export_url)
  const a = document.createElement('a')
  a.href = url
  a.download = `${model.model_name || 'model'}.glb`
  a.click()
}

function retryLoad(): void {
  const model = activeModel.value
  if (model) loadModel(model.export_url)
}

onMounted(() => {
  const container = containerRef.value
  if (!container) return
  initScene(container)
  if (activeModel.value) loadModel(activeModel.value.export_url)
  animate()
  resizeObserver = new ResizeObserver(handleResize)
  resizeObserver.observe(container)
})

onUnmounted(() => {
  cancelAnimationFrame(animFrameId)
  resizeObserver?.disconnect()
  if (loadedModel) disposeModel(loadedModel)
  controls?.dispose()
  renderer?.dispose()
  renderer = null
  scene = null
  camera = null
  controls = null
  loadedModel = null
})
</script>

<template>
  <div class="side-cad">
    <!-- Header -->
    <div class="side-cad__header">
      <div class="side-cad__name">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        <span class="side-cad__name-text">{{ activeModel?.model_name ?? '3D Model' }}</span>
      </div>
      <button class="side-cad__close" title="Chiudi pannello 3D" @click="emit('close')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>

    <!-- Canvas -->
    <div ref="containerRef" class="side-cad__canvas">
      <div v-if="loading" class="side-cad__overlay">
        <div class="side-cad__spinner" />
        <span class="side-cad__overlay-text">Caricamento modello 3Dâ€¦</span>
      </div>
      <div v-if="errorMsg" class="side-cad__overlay side-cad__overlay--error">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
          stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
        <span class="side-cad__overlay-text">{{ errorMsg }}</span>
        <button class="side-cad__retry-btn" @click="retryLoad">Riprova</button>
      </div>
      <p v-if="!loading && !errorMsg" class="side-cad__hint">
        Trascina per orbitare Â· Scroll per zoom
      </p>
    </div>

    <!-- Footer: navigation + controls -->
    <div class="side-cad__footer">
      <!-- Multi-model navigation -->
      <div v-if="hasMultiple" class="side-cad__nav">
        <button class="side-cad__nav-btn" :disabled="!canPrev" title="Modello precedente" @click="goPrev">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span class="side-cad__nav-label">{{ activeIndex + 1 }} / {{ models.length }}</span>
        <button class="side-cad__nav-btn" :disabled="!canNext" title="Modello successivo" @click="goNext">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>

      <!-- Controls -->
      <div class="side-cad__controls">
        <button class="side-cad__btn" :class="{ 'side-cad__btn--active': autoRotate }" title="Auto-rotazione"
          @click="toggleAutoRotate">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-6.22-8.56" />
            <polyline points="21 3 21 12 12 12" />
          </svg>
        </button>
        <button class="side-cad__btn" :class="{ 'side-cad__btn--active': wireframe }" title="Wireframe"
          @click="toggleWireframe">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="12" y1="3" x2="12" y2="21" />
          </svg>
        </button>
        <button class="side-cad__btn" title="Reset camera" @click="resetCamera">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v4m0 12v4M2 12h4m12 0h4" />
          </svg>
        </button>
        <div class="side-cad__divider" />
        <button class="side-cad__btn" title="Scarica GLB" @click="downloadModel">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* â”€â”€ Side panel container â”€â”€ */
.side-cad {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-0);
  border-left: 1px solid var(--border);
}

/* â”€â”€ Header â”€â”€ */
.side-cad__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  flex-shrink: 0;
}

.side-cad__name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.side-cad__name svg {
  flex-shrink: 0;
  color: var(--accent);
  opacity: 0.5;
}

.side-cad__name-text {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-cad__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: color 0.15s, background 0.15s;
}

.side-cad__close:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

/* â”€â”€ Canvas â”€â”€ */
.side-cad__canvas {
  position: relative;
  flex: 1;
  min-height: 0;
  background: var(--surface-0);
}

.side-cad__canvas :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}

/* â”€â”€ Overlays â”€â”€ */
.side-cad__overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  background: var(--surface-0);
  z-index: 1;
  pointer-events: none;
}

.side-cad__overlay--error {
  color: var(--danger);
  pointer-events: auto;
}

.side-cad__overlay-text {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.side-cad__overlay--error .side-cad__overlay-text {
  color: var(--danger);
}

.side-cad__retry-btn {
  margin-top: 8px;
  padding: 4px 14px;
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.side-cad__retry-btn:hover {
  background: var(--surface-3);
}

.side-cad__spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: side-cad-spin 0.8s linear infinite;
}

@keyframes side-cad-spin {
  to {
    transform: rotate(360deg);
  }
}

.side-cad__hint {
  position: absolute;
  bottom: var(--space-2);
  left: 50%;
  transform: translateX(-50%);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0.35;
  pointer-events: none;
  white-space: nowrap;
  transition: opacity 0.3s;
}

.side-cad__canvas:hover .side-cad__hint {
  opacity: 0;
}

/* â”€â”€ Footer: nav + controls â”€â”€ */
.side-cad__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1-5) var(--space-3);
  flex-shrink: 0;
  gap: var(--space-2);
}

/* â”€â”€ Multi-model navigation â”€â”€ */
.side-cad__nav {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.side-cad__nav-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.side-cad__nav-btn:hover:not(:disabled) {
  color: var(--text-primary);
  background: var(--surface-hover);
}

.side-cad__nav-btn:disabled {
  opacity: 0.25;
  cursor: default;
}

.side-cad__nav-label {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: center;
}

/* â”€â”€ Controls â”€â”€ */
.side-cad__controls {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.side-cad__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}

.side-cad__btn:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

.side-cad__btn--active {
  color: var(--accent);
  background: var(--accent-dim);
  border-color: var(--accent-border);
}

.side-cad__divider {
  width: 1px;
  height: 14px;
  background: var(--border);
  margin: 0 var(--space-0-5);
}
</style>
