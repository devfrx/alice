<script setup lang="ts">
/**
 * ArtifactPreview3D.vue — Compact, autorotating 3D preview for board cards.
 *
 * Streamlined fork of {@link CADViewer.vue}: no toolbar, no pointer
 * controls, just a continuously orbiting camera. Designed for grid
 * thumbnails — light footprint, theme-aware background.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { resolveBackendUrl } from '../../services/api'
import AppIcon from '../ui/AppIcon.vue'
import type { Artifact } from '../../types/artifacts'

const props = defineProps<{
    /** Artifact whose binary should be rendered. */
    artifact: Artifact
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let animFrameId = 0
let resizeObserver: ResizeObserver | null = null
let loadedModel: THREE.Group | null = null

const BG_COLOR = 0x161616 /* matches --surface-0 */
let pivot = new THREE.Group()

function initScene(container: HTMLDivElement): void {
    const w = container.clientWidth
    const h = container.clientHeight

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(w, h)
    renderer.setClearColor(BG_COLOR)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.0
    container.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 200)
    camera.position.set(2.6, 1.6, 2.6)
    camera.lookAt(0, 0, 0)

    /* Warm three-point lighting matching CADViewer */
    scene.add(new THREE.AmbientLight(0xfaf5ee, 0.45))
    const key = new THREE.DirectionalLight(0xfff5e6, 0.85)
    key.position.set(4, 6, 5)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xe8dcc8, 0.35)
    fill.position.set(-3, 3, -2)
    scene.add(fill)

    pivot = new THREE.Group()
    scene.add(pivot)
}

function fitToModel(model: THREE.Object3D): void {
    if (!camera) return
    const box = new THREE.Box3().setFromObject(model)
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z) || 1
    /* Recenter the model on its pivot so rotation looks balanced. */
    model.position.sub(center)
    const fov = camera.fov * (Math.PI / 180)
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.7
    camera.position.set(dist * 0.7, dist * 0.45, dist * 0.7)
    camera.near = dist * 0.01
    camera.far = dist * 20
    camera.updateProjectionMatrix()
    camera.lookAt(0, 0, 0)
}

function loadModel(): void {
    if (!scene) return
    const url = resolveBackendUrl(props.artifact.download_url)
    if (!url) {
        errorMsg.value = 'URL non valido'
        loading.value = false
        return
    }
    const loader = new GLTFLoader()
    loader.load(
        url,
        (gltf) => {
            loadedModel = gltf.scene
            pivot.add(loadedModel)
            fitToModel(loadedModel)
            loading.value = false
        },
        undefined,
        () => {
            errorMsg.value = 'Anteprima non disponibile'
            loading.value = false
        },
    )
}

function animate(): void {
    animFrameId = requestAnimationFrame(animate)
    pivot.rotation.y += 0.006
    if (renderer && scene && camera) renderer.render(scene, camera)
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

onMounted(() => {
    const container = containerRef.value
    if (!container) return
    initScene(container)
    loadModel()
    animate()
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)
})

onUnmounted(() => {
    cancelAnimationFrame(animFrameId)
    resizeObserver?.disconnect()
    if (loadedModel) {
        loadedModel.traverse((child) => {
            if (child instanceof THREE.Mesh) {
                child.geometry?.dispose()
                const m = child.material
                if (Array.isArray(m)) m.forEach((mat) => mat.dispose())
                else if (m) (m as THREE.Material).dispose()
            }
        })
    }
    renderer?.dispose()
    renderer = null
    scene = null
    camera = null
    loadedModel = null
})
</script>

<template>
    <div ref="containerRef" class="artifact-preview-3d">
        <div v-if="loading" class="artifact-preview-3d__overlay">
            <div class="artifact-preview-3d__spinner" />
        </div>
        <div v-if="errorMsg" class="artifact-preview-3d__overlay artifact-preview-3d__overlay--error">
            <AppIcon name="circle-x" :size="20" />
            <span>{{ errorMsg }}</span>
        </div>
    </div>
</template>

<style scoped>
.artifact-preview-3d {
    position: relative;
    width: 100%;
    height: 100%;
    background: var(--surface-0);
    overflow: hidden;
    border-radius: var(--radius-sm);
}

.artifact-preview-3d :deep(canvas) {
    display: block;
    width: 100% !important;
    height: 100% !important;
}

.artifact-preview-3d__overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    background: var(--surface-0);
    color: var(--text-muted);
    font-size: var(--text-xs);
    pointer-events: none;
}

.artifact-preview-3d__overlay--error {
    color: var(--danger, #d4624a);
}

.artifact-preview-3d__spinner {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid var(--accent-border);
    border-top-color: var(--accent);
    animation: artifact-preview-spin 0.9s linear infinite;
}

@keyframes artifact-preview-spin {
    to {
        transform: rotate(360deg);
    }
}
</style>
