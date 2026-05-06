<script setup lang="ts">
/**
 * CADViewer.vue — Interactive 3D model viewer for TRELLIS-generated GLB files.
 *
 * Uses Three.js + GLTFLoader with OrbitControls for drag/scroll/pinch
 * interaction. Auto-fits the camera to the loaded model bounding box.
 * Visual style matches the AL\CE dark charcoal + warm cream theme.
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { resolveBackendUrl } from '../../services/api'
import { useArtifactsStore } from '../../stores/artifacts'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{
    /** Relative or absolute URL to the GLB model file. */
    modelUrl: string
    /** Display name for the model (shown in toolbar). */
    modelName?: string
    /** Optional artifact id; when provided, exposes pin/unpin in the toolbar. */
    artifactId?: string
}>()

const artifactsStore = useArtifactsStore()

/** Reactive pin status looked up from the artifacts store. */
const pinned = computed<boolean>(() => {
    if (!props.artifactId) return false
    return artifactsStore.findById(props.artifactId)?.pinned ?? false
})

const togglePinPending = ref(false)

async function togglePin(): Promise<void> {
    if (!props.artifactId || togglePinPending.value) return
    togglePinPending.value = true
    try {
        await artifactsStore.togglePin(props.artifactId)
    } catch (err) {
        console.error('[CADViewer] togglePin failed:', err)
    } finally {
        togglePinPending.value = false
    }
}

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

/* Saved camera state for reset */
let initialCameraPos = new THREE.Vector3()
let initialControlsTarget = new THREE.Vector3()

/* Theme-consistent palette */
const BG_COLOR = 0x161616      /* --bg-primary */
const GRID_MAIN = 0x2a2a2a    /* --surface-3 */
const GRID_SUB = 0x1c1c1c     /* --surface-1 */
/* ACCENT_CREAM 0xe8dcc8 — available for highlights if needed */

function initScene(container: HTMLDivElement): void {
    const w = container.clientWidth
    const h = container.clientHeight

    /* Renderer */
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(w, h)
    renderer.setClearColor(BG_COLOR)
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.0
    renderer.outputColorSpace = THREE.SRGBColorSpace
    container.appendChild(renderer.domElement)

    /* Scene */
    scene = new THREE.Scene()
    scene.fog = new THREE.Fog(BG_COLOR, 8, 28)

    /* PBR image-based lighting — required for TRELLIS GLB models that
       ship metallic/roughness PBR materials.  Without an environment
       map, metallic surfaces sample a black environment and the model
       renders almost completely dark even with directional lights. */
    const pmrem = new THREE.PMREMGenerator(renderer)
    pmrem.compileEquirectangularShader()
    const envScene = new RoomEnvironment()
    scene.environment = pmrem.fromScene(envScene, 0.04).texture
    envScene.traverse((c) => {
        if (c instanceof THREE.Mesh) c.geometry?.dispose()
    })
    pmrem.dispose()

    /* Camera */
    camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 1000)
    camera.position.set(3, 2, 3)

    /* Controls */
    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.06
    controls.autoRotate = true
    controls.autoRotateSpeed = 1.5
    controls.maxPolarAngle = Math.PI * 0.85
    controls.minDistance = 0.5

    /* Lighting — warm three-point setup matching cream palette */
    const ambient = new THREE.AmbientLight(0xfaf5ee, 0.35)
    scene.add(ambient)

    const keyLight = new THREE.DirectionalLight(0xfff5e6, 0.9)
    keyLight.position.set(4, 6, 5)
    scene.add(keyLight)

    const fillLight = new THREE.DirectionalLight(0xe8dcc8, 0.3)
    fillLight.position.set(-3, 3, -2)
    scene.add(fillLight)

    const rimLight = new THREE.DirectionalLight(0xffffff, 0.2)
    rimLight.position.set(0, -2, -4)
    scene.add(rimLight)

    /* Ground plane — subtle reflective surface */
    const groundGeo = new THREE.CircleGeometry(6, 64)
    const groundMat = new THREE.MeshStandardMaterial({
        color: 0x1c1c1c,
        roughness: 0.85,
        metalness: 0.05,
        transparent: true,
        opacity: 0.6,
    })
    const ground = new THREE.Mesh(groundGeo, groundMat)
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.001
    ground.receiveShadow = true
    scene.add(ground)

    /* Grid — subtle concentric rings */
    const grid = new THREE.GridHelper(12, 24, GRID_MAIN, GRID_SUB)
    const gridMat = grid.material as THREE.Material
    gridMat.transparent = true
    gridMat.opacity = 0.3
    scene.add(grid)
}

function fitCameraToModel(model: THREE.Object3D): void {
    if (!camera || !controls) return

    const box = new THREE.Box3().setFromObject(model)
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z)
    const fov = camera.fov * (Math.PI / 180)
    const dist = maxDim / (2 * Math.tan(fov / 2)) * 1.8

    camera.position.set(center.x + dist * 0.6, center.y + dist * 0.35, center.z + dist * 0.6)
    controls.target.copy(center)
    camera.near = dist * 0.01
    camera.far = dist * 20
    camera.updateProjectionMatrix()
    controls.update()

    initialCameraPos.copy(camera.position)
    initialControlsTarget.copy(controls.target)
}

function loadModel(): void {
    if (!scene) return

    const url = resolveBackendUrl(props.modelUrl)
    const loader = new GLTFLoader()

    loader.load(
        url,
        (gltf) => {
            loadedModel = gltf.scene
            scene!.add(loadedModel)
            fitCameraToModel(loadedModel)
            loading.value = false
        },
        undefined,
        (err) => {
            errorMsg.value = err instanceof Error ? err.message : 'Failed to load 3D model'
            loading.value = false
        }
    )
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

/* --- Toolbar actions --- */

function toggleAutoRotate(): void {
    autoRotate.value = !autoRotate.value
}

function toggleWireframe(): void {
    wireframe.value = !wireframe.value
    if (!loadedModel) return
    loadedModel.traverse((child) => {
        if (child instanceof THREE.Mesh && child.material) {
            const mat = child.material as THREE.Material
            if ('wireframe' in mat) {
                ; (mat as THREE.MeshStandardMaterial).wireframe = wireframe.value
            }
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
    const url = resolveBackendUrl(props.modelUrl)
    const a = document.createElement('a')
    a.href = url
    a.download = props.modelName ? `${props.modelName}.glb` : 'model.glb'
    a.click()
}

/* --- Lifecycle --- */

onMounted(() => {
    const container = containerRef.value
    if (!container) return

    initScene(container)
    loadModel()
    animate()

    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)

    /* Lazy-fetch artifact so the pin state reflects the persisted value
       even on first render after a fresh app load. */
    if (props.artifactId && !artifactsStore.findById(props.artifactId)) {
        artifactsStore.fetchById(props.artifactId).catch(() => { /* best-effort */ })
    }
})

onUnmounted(() => {
    cancelAnimationFrame(animFrameId)
    resizeObserver?.disconnect()

    if (loadedModel) {
        loadedModel.traverse((child) => {
            if (child instanceof THREE.Mesh) {
                child.geometry?.dispose()
                if (Array.isArray(child.material)) {
                    child.material.forEach((m) => {
                        m.map?.dispose()
                        m.dispose()
                    })
                } else if (child.material) {
                    ; (child.material as THREE.MeshStandardMaterial).map?.dispose()
                    child.material.dispose()
                }
            }
        })
    }

    controls?.dispose()
    renderer?.dispose()
    scene?.environment?.dispose()
    renderer = null
    scene = null
    camera = null
    controls = null
    loadedModel = null
})
</script>

<template>
    <div class="cad-viewer">
        <!-- Toolbar -->
        <div class="cad-viewer__toolbar">
            <div class="cad-viewer__title-group">
                <AppIcon name="box-3d" :size="14" :stroke-width="1.5" class="cad-viewer__badge" />
                <span class="cad-viewer__title">{{ modelName ?? '3D Model' }}</span>
                <span class="cad-viewer__format">.glb</span>
            </div>
            <div class="cad-viewer__actions">
                <button class="cad-viewer__btn" :class="{ 'cad-viewer__btn--active': autoRotate }" title="Auto-rotate"
                    @click="toggleAutoRotate">
                    <AppIcon name="auto-rotate" :size="14" />
                </button>
                <button class="cad-viewer__btn" :class="{ 'cad-viewer__btn--active': wireframe }" title="Wireframe"
                    @click="toggleWireframe">
                    <AppIcon name="wireframe" :size="14" />
                </button>
                <button class="cad-viewer__btn" title="Reset camera" @click="resetCamera">
                    <AppIcon name="crosshair" :size="14" />
                </button>
                <div class="cad-viewer__divider" />
                <button v-if="artifactId" class="cad-viewer__btn" :class="{ 'cad-viewer__btn--active': pinned }"
                    :title="pinned ? 'Rimuovi dalla bacheca' : 'Salva in bacheca'" :disabled="togglePinPending"
                    @click="togglePin">
                    <AppIcon name="pin" :size="14" />
                </button>
                <button class="cad-viewer__btn cad-viewer__btn--download" title="Download GLB" @click="downloadModel">
                    <AppIcon name="download" :size="14" />
                </button>
            </div>
        </div>

        <!-- Canvas container -->
        <div ref="containerRef" class="cad-viewer__canvas">
            <!-- Loading overlay -->
            <div v-if="loading" class="cad-viewer__overlay">
                <div class="cad-viewer__spinner" />
                <span class="cad-viewer__overlay-text">Caricamento modello 3D…</span>
            </div>

            <!-- Error overlay -->
            <div v-if="errorMsg" class="cad-viewer__overlay cad-viewer__overlay--error">
                <AppIcon name="circle-x" :size="28" :stroke-width="1.5" />
                <span class="cad-viewer__overlay-text">{{ errorMsg }}</span>
            </div>

            <!-- Interaction hint (bottom-right) -->
            <div v-if="!loading && !errorMsg" class="cad-viewer__hint">
                Drag to orbit · Scroll to zoom
            </div>
        </div>
    </div>
</template>

<style scoped>
.cad-viewer {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    overflow: hidden;
    margin-top: var(--space-2);
    background: var(--surface-0);
    box-shadow: var(--shadow-md);
    max-width: 560px;
}

/* ── Toolbar ─────────────────────────────────── */

.cad-viewer__toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-3);
    background: var(--surface-1);
    border-bottom: 1px solid var(--border);
    gap: var(--space-3);
}

.cad-viewer__title-group {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
}

.cad-viewer__badge {
    flex-shrink: 0;
    color: var(--accent);
    opacity: 0.7;
}

.cad-viewer__title {
    font-size: var(--text-sm);
    color: var(--text-primary);
    font-weight: 500;
    font-family: var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.cad-viewer__format {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
    background: var(--surface-3);
    padding: 1px var(--space-1-5);
    border-radius: var(--radius-xs);
    flex-shrink: 0;
}

.cad-viewer__actions {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
}

.cad-viewer__divider {
    width: 1px;
    height: 16px;
    background: var(--border);
    margin: 0 var(--space-0-5);
}

.cad-viewer__btn {
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

.cad-viewer__btn:hover {
    color: var(--text-primary);
    background: var(--surface-hover);
}

.cad-viewer__btn--active {
    color: var(--accent);
    background: var(--accent-dim);
    border-color: var(--accent-border);
}

.cad-viewer__btn--download:hover {
    color: var(--accent);
}

/* ── Canvas ──────────────────────────────────── */

.cad-viewer__canvas {
    position: relative;
    width: 100%;
    height: 380px;
    background: var(--surface-0);
}

.cad-viewer__canvas canvas {
    display: block;
    width: 100% !important;
    height: 100% !important;
}

/* ── Overlays ────────────────────────────────── */

.cad-viewer__overlay {
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

.cad-viewer__overlay--error {
    color: var(--danger);
    pointer-events: auto;
}

.cad-viewer__overlay-text {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    letter-spacing: 0.02em;
}

.cad-viewer__overlay--error .cad-viewer__overlay-text {
    color: var(--danger);
}

.cad-viewer__spinner {
    width: 28px;
    height: 28px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: cad-spin 0.8s linear infinite;
}

@keyframes cad-spin {
    to {
        transform: rotate(360deg);
    }
}

/* ── Interaction hint ────────────────────────── */

.cad-viewer__hint {
    position: absolute;
    bottom: var(--space-2);
    right: var(--space-3);
    font-size: var(--text-2xs);
    color: var(--text-muted);
    opacity: 0.5;
    pointer-events: none;
    transition: opacity 0.3s;
}

.cad-viewer__canvas:hover .cad-viewer__hint {
    opacity: 0;
}
</style>
